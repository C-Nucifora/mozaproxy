"""Native editor for per-game mappings. Editing and learning are passive."""
from copy import deepcopy
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QCheckBox, QPushButton, QScrollArea)
from .game_mappings import (default_mapping, validate_mapping, AXIS_ROLES,
                            SOURCE_AXES, SOURCE_BUTTONS)
from .profiles import R25_BUTTON_PRIORITY


class GameMappingEditor(QWidget):
    save_requested = Signal(dict)
    start_requested = Signal(str)
    apply_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game_id = None
        self.drafts, self.saved_values = {}, {}
        self.loading = False
        self.learning = None
        self.pressed = set()
        self.busy = self.running = self.system_mode = False
        self.storage_error = None
        self.live_game = None
        self.live_status = {}
        layout = QVBoxLayout(self)
        self.target = QComboBox()
        self.target.addItem('Direct physical wheel (baseline)', 'direct')
        self.target.addItem('Logitech G920 layout (experimental)', 'g920')
        self.target.setAccessibleName('Wheel layout expected by this game')
        layout.addWidget(self.target)
        self.description = QLabel('')
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.fields = QWidget()
        grid = QGridLayout(self.fields)
        grid.setColumnStretch(1, 1)
        for i, text in enumerate(('Game wheel control', 'R25 input', 'Direction / assign')):
            grid.addWidget(QLabel(text), 0, i)
        self.axis_sources, self.axis_inverts, self.axis_values = {}, {}, {}
        row = 1
        for role in AXIS_ROLES:
            title = QLabel(role.title())
            combo = QComboBox()
            for code, name in SOURCE_AXES.items(): combo.addItem(name, code)
            combo.setAccessibleName(f'R25 input for {role}')
            title.setBuddy(combo)
            invert = QCheckBox('Reverse')
            invert.setAccessibleName(f'Reverse {role}')
            value = QLabel('No reading')
            value.setAccessibleName(f'{role} mapped input')
            controls = QHBoxLayout(); controls.addWidget(invert); controls.addWidget(value)
            grid.addWidget(title,row,0); grid.addWidget(combo,row,1); grid.addLayout(controls,row,2)
            self.axis_sources[role], self.axis_inverts[role], self.axis_values[role] = combo, invert, value
            combo.currentIndexChanged.connect(self.changed); invert.toggled.connect(self.changed)
            row += 1
        self.button_sources, self.learn_buttons = [], []
        for index in range(11):
            title = QLabel(f'Button {index+1}')
            combo = QComboBox(); combo.addItem('Unassigned', None)
            for code in R25_BUTTON_PRIORITY: self._add_button(combo,code)
            combo.setAccessibleName(f'R25 input for game wheel button {index+1}')
            title.setBuddy(combo)
            learn = QPushButton('Learn')
            learn.setAccessibleName(f'Learn R25 input for game wheel button {index+1}')
            learn.clicked.connect(lambda checked=False, i=index: self.learn_button(i))
            grid.addWidget(title,row,0); grid.addWidget(combo,row,1); grid.addWidget(learn,row,2)
            combo.currentIndexChanged.connect(self.changed)
            self.button_sources.append(combo); self.learn_buttons.append(learn)
            row += 1
        self.hat = QCheckBox('Forward the R25 directional pad to the game')
        self.hat.toggled.connect(self.changed)
        grid.addWidget(self.hat,row,0,1,3)
        grid.setRowStretch(row+1,1)
        self.scroll.setWidget(self.fields); layout.addWidget(self.scroll,1)
        self.message = QLabel('Select a game.'); self.message.setWordWrap(True)
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        self.reset_button = QPushButton('Discard edits')
        self.reset_button.clicked.connect(self.discard)
        self.save_button = QPushButton('Save mapping')
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.mapping()))
        self.start_button = QPushButton('Start saved mapping')
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self.game_id))
        self.apply_button = QPushButton('Apply saved mapping live')
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(self.game_id))
        actions.addWidget(self.reset_button); actions.addStretch()
        actions.addWidget(self.save_button); actions.addWidget(self.start_button); actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self.target.currentIndexChanged.connect(self.target_changed)
        self.refresh_actions()

    @staticmethod
    def _add_button(combo,code):
        if combo.findData(code) < 0:
            combo.addItem(SOURCE_BUTTONS.get(code, f'R25 button {code}'),code)

    @property
    def dirty(self):
        return self.game_id is not None and self.raw_mapping() != self.saved_values[self.game_id]

    def raw_mapping(self):
        data = {'version':1,'game_id':self.game_id,'target':self.target.currentData()}
        if data['target'] == 'g920':
            data.update(axes={role:{'source':self.axis_sources[role].currentData(),
                                    'inverted':self.axis_inverts[role].isChecked()} for role in AXIS_ROLES},
                        buttons=[combo.currentData() for combo in self.button_sources], hat=self.hat.isChecked())
        return data

    def mapping(self): return validate_mapping(self.raw_mapping())

    def select_game(self, game_id, saved):
        if self.game_id is not None:
            self.drafts[self.game_id] = self.raw_mapping()
        self.learning = None
        self.game_id = game_id
        self.saved_values[game_id] = deepcopy(saved)
        self.load(self.drafts.get(game_id,saved))

    def load(self, data):
        self.loading = True
        self.target.setCurrentIndex(self.target.findData(data['target']))
        draft = data if data['target'] == 'g920' else default_mapping(self.game_id,'g920')
        for role,item in draft['axes'].items():
            self.axis_sources[role].setCurrentIndex(self.axis_sources[role].findData(item['source']))
            self.axis_inverts[role].setChecked(item['inverted'])
        for combo,code in zip(self.button_sources,draft['buttons']):
            if code is not None: self._add_button(combo,code)
            combo.setCurrentIndex(combo.findData(code))
        self.hat.setChecked(draft['hat'])
        self.loading = False
        self.changed()

    def target_changed(self):
        if self.loading or self.game_id is None: return
        self.learning = None
        self.load(default_mapping(self.game_id,self.target.currentData()))

    def changed(self):
        if not self.loading: self.refresh_actions()

    def discard(self):
        if self.game_id is None: return
        self.learning = None
        self.drafts.pop(self.game_id,None)
        self.load(self.saved_values[self.game_id])

    def saved(self,data):
        data = {k:v for k,v in data.items() if k != 'id'}
        self.saved_values[data['game_id']] = deepcopy(data)
        self.drafts[data['game_id']] = deepcopy(data)
        self.refresh_actions()

    def learn_button(self,index):
        if self.learning == index: self.learning = None
        else: self.learning = index
        self.refresh_actions()

    def observe(self,device):
        pressed = {item['code'] for item in device.get('buttons',[]) if item.get('pressed')}
        fresh = pressed - self.pressed
        self.pressed = pressed
        if self.learning is not None and len(fresh) == 1 and len(pressed) == 1:
            combo = self.button_sources[self.learning]; code = fresh.pop()
            self._add_button(combo,code)
            self.learning = None
            combo.setCurrentIndex(combo.findData(code))
        axes = {item['code']:item for item in device.get('axes',[])}
        for role,combo in self.axis_sources.items():
            axis = axes.get(combo.currentData())
            value = 'No reading'
            if axis and axis['max'] > axis['min']:
                normalized = max(0,min(1,(axis['raw']-axis['min'])/(axis['max']-axis['min'])))
                if self.axis_inverts[role].isChecked(): normalized=1-normalized
                value = f'{normalized*100:.1f}% output'
            self.axis_values[role].setText(value)
        self.refresh_actions()

    def set_runtime(self, *, busy=False, running=False, system_mode=False, storage_error=None, live_game=None, live_status=None):
        self.busy, self.running, self.system_mode, self.storage_error = busy,running,system_mode,storage_error
        self.live_game, self.live_status = live_game, live_status or {}
        if busy: self.learning = None
        self.refresh_actions()

    def refresh_actions(self):
        valid = self.game_id is not None
        error = None
        if valid:
            try: self.mapping()
            except ValueError as exc: valid=False; error=str(exc)
        mapped = self.target.currentData() == 'g920'
        self.scroll.setVisible(mapped)
        self.description.setText(
            'Fixed G920 layout: four axes, eleven buttons and a directional pad. '
            'Assignments are experimental. Button numbers are one-based; confirm their actions in the game. '
            'Steering is linear with no added deadzone. FFB passes through unchanged.' if mapped else
            'Uses the physical wheel. No virtual wheel or automatic changes to your existing game setup.')
        for i,learn in enumerate(self.learn_buttons): learn.setText('Cancel' if self.learning == i else 'Learn')
        self.fields.setEnabled(not self.busy)
        self.target.setEnabled(self.game_id is not None and not self.busy)
        dirty = self.dirty if self.game_id is not None else False
        self.reset_button.setEnabled(dirty and not self.busy)
        self.save_button.setEnabled(valid and dirty and not self.busy and not self.storage_error)
        self.start_button.setEnabled(valid and mapped and not dirty and not self.busy and not self.running and not self.system_mode and not self.storage_error)
        live = self.running and self.live_game == self.game_id
        self.apply_button.setVisible(live)
        self.apply_button.setEnabled(valid and mapped and not dirty and not self.busy and not self.storage_error
                                     and self.live_status.get('mapping') != self.saved_values.get(self.game_id))
        text = self.storage_error or error
        if not text:
            if self.learning is not None: text=f'Release other controls, then press one R25 button for slot {self.learning+1}.'
            elif dirty: text='Unsaved mapping. The running inputs stay unchanged until you save and apply.'
            elif self.system_mode: text='Save mappings here. Starting a custom layout currently requires local app mode.'
            elif self.running and not mapped: text='Direct access saved. Stop the relay from Overview before using the physical wheel.'
            elif live and self.live_status.get('error'): text='Live mapping rejected: ' + self.live_status['error']
            elif live and self.live_status.get('mapping') == self.saved_values.get(self.game_id): text='Saved mapping is active on the connected virtual wheel.'
            elif live: text='Save edits, then apply live. The virtual wheel stays connected.'
            elif self.running: text='Relay running. Saved changes take effect on the next start.'
            elif mapped: text='Saved. Close the game before starting this mapping, then relaunch with its isolation setup.'
            else: text='Baseline selected. Keep the relay stopped for direct access.'
        self.message.setText(text)
