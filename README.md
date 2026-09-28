# Hong Kong International Airport Manager

Live departures and arrivals, flight history, gate details, airport maps, approaches and a 3D airport view. Mobile screens default to flight cards; the flipboard remains available from the board toolbar.

## Run locally

```sh
cd AirportManager
python3 hkia_live_server.py --port 8461
```

Open http://localhost:8461/. To use a phone on the same Wi-Fi, add `--host 0.0.0.0` and open `http://<computer-LAN-IP>:8461/` on the phone.

Optional API keys are read from environment variables `ADBX_KEY`, `GEO_KEY` and `OPENAIP_KEY`, or local files described in `AirportManager/keys/keys_README.txt`. Never commit key files. Saved photoreal credentials are returned only to loopback clients.

## Development

Install Shapely to rebuild airport geometry (`python3 -m pip install shapely`). Run `python3 render_cached_page.py` inside AirportManager to rebuild the page from the bundled dataset, or `python3 build_gate_map.py` to refresh the complete dataset.

```sh
cd AirportManager
node tests/board_regression.cjs
python3 -m unittest discover -s tests -p 'test_*.py'
```

The schematic is not to scale. Geographic and 3D views use airport geometry; the 3D ground footprint is approximate.

## Hosting

`render.yaml` configures the live Python backend. The GitHub Pages workflow publishes the bundled frontend and points API requests to that backend. Live features require the backend to be available. Local keys and runtime caches are excluded from new commits.
