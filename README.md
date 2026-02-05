[README.md](https://github.com/user-attachments/files/25094899/README.md)
[README.md](https://github.com/user-attachments/files/25094899/README.md)
# DOI Lookup (Streamlit)

Strict title matching DOI lookup using Crossref + DBLP.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud
- Add `CROSSREF_MAILTO` in Streamlit Secrets (recommended), e.g.
  ```toml
  CROSSREF_MAILTO="you@example.com"
  ```
- Deploy `app.py` as the entrypoint.

## Input format
Each line:
- `Title`
- `Title<TAB>AuthorSurname` (recommended to reduce false matches)

Matching is STRICT: normalized title must match exactly. If not found, the app can show Top-3 candidates (not auto-selected).
