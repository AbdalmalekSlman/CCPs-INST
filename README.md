# CCPs-INST (CMMS)

Flask + SQLite maintenance management system. Front end is plain HTML/JS in `static/`.

## Run on a Linux VPS (behind nginx)

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
SECRET_KEY="<long random string>" PORT=8100 venv/bin/python app.py
```

The app listens on `127.0.0.1` only (default port 8100); point nginx `proxy_pass` at `http://127.0.0.1:8100`.

### Environment variables

| Name | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | yes | Signs login sessions. The app refuses to start without it. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| `PORT` | no | Local port to listen on (default `8100`). |

The app uses no Telegram token or other API keys. The database `cmms.db` and the `uploads/` folder are created in the app folder and are ignored by git.
