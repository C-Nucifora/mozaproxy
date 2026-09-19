# Browser regression checks

Start the local app with `.venv/bin/python -m mozaproxy.web`. The regression
script intercepts every `/api/` request and uses fake device state. It cannot
connect settings, start the relay, or send device writes through the server.
It checks profile overrides, invalid draft handling, route persistence and
connection errors against the actual JavaScript and HTML.

Requires Chromium at `/usr/bin/chromium`, Node, and the `playwright` package.
An isolated installation keeps browser tooling out of the runtime dependencies:

```sh
npm install --prefix /tmp/mozaproxy-browser playwright
NODE_PATH=/tmp/mozaproxy-browser/node_modules node tests/browser/app-regressions.cjs
```

For manual hardware validation, connect settings to read the wheel. Changing
fields prepares a draft; Apply sends configuration writes. Motor and game tests
need a person at the wheel. Desktop and mobile layout captures made during
implementation are local artifacts under `.impeccable/review/`, not fixture data.
