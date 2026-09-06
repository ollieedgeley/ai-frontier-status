# Security boundaries

The plugin fetches public status data for the providers selected by the user. Requests disclose the client's IP address and plugin User-Agent to those providers. It sends no credentials or local files.

Endpoints are defined in companies.json. Fetches require HTTPS on port 443, valid certificates, public destination addresses, and at most three redirects on the original host. The socket connects to the address checked by the helper, preserving the hostname for TLS verification. Connections are direct: environment HTTP/HTTPS proxies are not used. Networks that require a proxy may report connection errors.

Each response is limited to 2 MiB. Compressed responses and XML DTDs/entities are rejected. Parsed data has limits on depth, nodes, collection sizes and string lengths; Nuxt expansion also detects cycles and has a shared work budget. Excessive input reports an unavailable status. Display-detail truncation occurs after status classification.

The helper uses at most eight threads and a kernel-enforced 60-second process deadline. Quickshell separately kills a fetch after 65 seconds, or a catalog command after five seconds. Stream collection is limited to 512 KiB of output and 4 KiB of errors. Failed fetches clear previous reports rather than displaying stale success.

Settings are saved through Omarchy's standard settings API. The plugin has no installer, self-updater, privileged operation, credential storage or third-party Python dependency. Provider changes can require catalog/parser maintenance; a successful fetch does not guarantee a provider's report is accurate.

## Regression checks

Run from this checkout:

```sh
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/model.test.mjs
QT_QPA_PLATFORM=offscreen quickshell -p ProcessSecurityTest.qml --no-color
```

The Quickshell check must print its PASS message. It exercises actual process timeout, recovery, output limits and failed-launch behavior without loading the desktop panel or changing user settings. Scanner warnings about the panel's qs.Ui/qs.Commons imports are expected in this isolated harness.
