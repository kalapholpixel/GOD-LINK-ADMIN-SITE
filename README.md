# PROPERTY-SALES-ADMIN

This repo provides a simple admin UI to edit site content for the client site. It stores content in `data/data.json`. When you update the JSON and deploy or push, the client site can load it via `../PROPERTY-SALES-ADMIN/data/data.json` (relative path used by the client site).

Quick run (serve locally):

```bash
python3 -m http.server 3000
```

Open `http://localhost:3000` and edit `data/data.json` via the admin UI.

Run the editable admin server (recommended):

```bash
python3 server.py
```

This starts a small HTTP server on port `3000` that accepts POST /save to persist `data/data.json`.