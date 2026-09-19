#!/usr/bin/env python3
"""Offline decoder for captured R25 PID reports. Never opens a hardware device.

Offsets are specific to tests/fixtures/r25-ultra-descriptor.bin. Supply complete
hex reports including the report ID. This tool neither captures nor sends them.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct


REPORTS = {
    1: ('set_effect', 22), 2: ('set_envelope', 14),
    5: ('set_constant_force', 4), 10: ('effect_operation', 4),
    11: ('block_free', 2), 12: ('device_control', 2), 13: ('device_gain', 2),
}
CONTROL_BITS = ('enable_actuators', 'disable_actuators', 'stop_all',
                'reset', 'pause', 'continue')
FEATURE_REPORTS = {17: ('create_effect', 4), 18: ('block_load', 5), 19: ('pool', 5)}


def decode_report(data):
    """Decode supported output reports from the exact R25 fixture layout."""
    if not data or data[0] not in REPORTS:
        raise ValueError('Unknown R25 output report ID; supported IDs: 1, 2, 5, 10, 11, 12, 13')
    name, length = REPORTS[data[0]]
    if len(data) < length:
        raise ValueError(f'{name} needs {length} bytes including its report ID; got {len(data)}')
    result = dict(report_id=data[0], name=name, report_bytes=length,
                  padding_bytes=len(data) - length, padding_nonzero=any(data[length:]),
                  observations=[])
    if data[0] in (1, 2, 5, 10, 11):
        result['effect_id'] = data[1]
        if not 1 <= data[1] <= 10:
            result['observations'].append('effect ID outside advertised slots 1..10')
    if data[0] == 1:
        duration, trigger_repeat, sample_period, start_delay = struct.unpack_from('<4H', data, 3)
        result.update(effect_type=data[2], duration_ms=duration,
                      infinite_duration=duration == 65535,
                      trigger_repeat_ms=trigger_repeat, sample_period_ms=sample_period,
                      start_delay_ms=start_delay, gain_raw=data[11],
                      trigger_button=data[12],
                      axes_enabled=[name for bit, name in enumerate(('X', 'Y')) if data[13] & (1 << bit)],
                      direction_enabled=bool(data[13] & 4),
                      direction_raw=list(struct.unpack_from('<2H', data, 14)),
                      type_specific_offsets=list(struct.unpack_from('<2H', data, 18)))
        if data[12] > 8:
            result['observations'].append(
                'trigger exceeds advertised maximum 8; PIDFF disables such triggers with zero')
        if any(value > 36000 for value in result['direction_raw']):
            result['observations'].append('direction exceeds descriptor maximum 36000')
    elif data[0] == 2:
        attack_level, fade_level, attack_ms, fade_ms = struct.unpack_from('<HHII', data, 2)
        result.update(attack_level_raw=attack_level, fade_level_raw=fade_level,
                      attack_ms=attack_ms, fade_ms=fade_ms)
    elif data[0] == 5:
        result['magnitude'] = struct.unpack_from('<h', data, 2)[0]
    elif data[0] == 10:
        result.update(operation={1: 'start', 2: 'start_solo', 3: 'stop'}.get(data[2], 'unknown'),
                      operation_raw=data[2], iterations=data[3])
    elif data[0] == 12:
        result['controls'] = [name for bit, name in enumerate(CONTROL_BITS) if data[1] & (1 << bit)]
        result['control_bits_raw'] = data[1]
    elif data[0] == 13:
        result['gain_raw'] = data[1]
    return result


def decode_feature(data):
    if not data or data[0] not in FEATURE_REPORTS:
        raise ValueError('Unknown R25 feature report ID')
    name, length = FEATURE_REPORTS[data[0]]
    if len(data) < length:
        raise ValueError(f'{name} needs {length} bytes including its report ID; got {len(data)}')
    result = dict(report_id=data[0], name=name, report_bytes=length,
                  padding_bytes=len(data) - length, padding_nonzero=any(data[length:]))
    if data[0] == 17:
        result.update(effect_type=data[1], byte_count=struct.unpack_from('<H', data, 2)[0] & 1023)
    elif data[0] == 18:
        result.update(effect_id=data[1], status={1: 'success', 2: 'full', 3: 'error'}.get(data[2], 'unknown'),
                      status_raw=data[2], pool_available=struct.unpack_from('<H', data, 3)[0])
    elif data[0] == 19:
        result.update(pool_size=struct.unpack_from('<H', data, 1)[0], simultaneous_effects=data[3],
                      device_managed=bool(data[4] & 1), shared_parameter_blocks=bool(data[4] & 2))
    return result


def decode_capture(lines):
    """Annotate bounded jdm_trace JSONL while retaining failures and unknown IDs."""
    records = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get('hex'), str):
                raise ValueError('Expected an object with a hex string')
            data = bytes.fromhex(record['hex'])
        except ValueError as exc:
            raise ValueError(f'Capture line {number}: {exc}') from exc
        record['decoded'] = None
        if data:
            try:
                if record.get('operation') == 'write':
                    record['decoded'] = decode_report(data)
                elif record.get('operation') in ('get_feature', 'set_feature'):
                    record['decoded'] = decode_feature(data)
            except ValueError as exc:
                record['decode_note'] = str(exc)
        records.append(record)
    return records


LOG_MARKERS = {
    'create_effect': ':dinput_device_CreateEffect ',
    'set_parameters': ':hid_joystick_effect_SetParameters iface ',
    'download': ':hid_joystick_effect_Download iface ',
    'start': ':hid_joystick_effect_Start iface ',
    'stop': ':hid_joystick_effect_Stop iface ',
    'unload': ':hid_joystick_effect_Unload iface ',
    'unknown_angle_unit': 'unknown angle unit caps ',
    'unknown_time_unit': 'unknown time unit caps ',
    'collection_parent_error': ' parent!',
    'hid_set_value_error': 'HidP_SetUsageValue returned ',
    'hid_set_usages_error': 'HidP_SetUsages returned ',
}


def summarize_log(lines):
    """Stream dinput diagnostics without loading the large input trace into RAM."""
    counts = Counter()
    first_lines = {}
    report_ids = {}
    parameter_flags = Counter()
    line_count = 0
    for line_count, line in enumerate(lines, 1):
        if ':dinput:' not in line:
            continue
        for key, marker in LOG_MARKERS.items():
            if marker in line:
                counts[key] += 1
                first_lines.setdefault(key, line_count)
        match = re.search(r'(device control|effect update|set constant force) id (\d+)', line)
        if match:
            report_ids.setdefault(match[1], set()).add(int(match[2]))
        if LOG_MARKERS['set_parameters'] in line:
            match = re.search(r'flags (0x[0-9a-f]+)', line)
            if match:
                parameter_flags[match[1]] += 1
    return dict(lines=line_count, counts=dict(counts), first_lines=first_lines,
                report_ids={name: sorted(values) for name, values in report_ids.items()},
                set_parameters_flags=dict(parameter_flags),
                outbound_report_bytes_available=False,
                limitation='Dinput call traces and input hex dumps do not show outbound PID bytes or effect parameter values.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--report-hex', help='Captured output report as hexadecimal, including report ID')
    source.add_argument('--log', type=Path, help='Archived Proton dinput log to summarize')
    source.add_argument('--capture', type=Path, help='Saved jdm_trace JSONL to decode')
    args = parser.parse_args(argv)
    try:
        if args.report_hex is not None:
            result = decode_report(bytes.fromhex(args.report_hex))
        elif args.log is not None:
            with args.log.open(errors='replace') as stream:
                result = summarize_log(stream)
        else:
            with args.capture.open() as stream:
                result = decode_capture(stream)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
