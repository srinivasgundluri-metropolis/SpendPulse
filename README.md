# spendPulse

Local-first credit card spend tracker. Upload statement **PDFs** (Amex today) or activity **CSV / Excel** exports (Apple Card, Citi, Chase, …). Transactions are categorized, tagged, and rolled into month-over-month views — coffee, dining, Tesla, transfers, and the rest.

Nothing leaves your machine. `data/` stays local and is gitignored.

## Features

- **Multi-issuer shell** — filter by card or club all cards into one YTD
- **PDF + CSV/Excel import** — spreadsheets split into calendar months automatically
- **Categories & tags** — coffee, avoidable, Tesla, Starbucks, Transfers, …
- **Dining** — cuisine + distinct restaurant rollups
- **Members** — cardholder share, leaders, MoM
- **LaunchAgent** (macOS) — keeps the local server running

## Quick start

```bash
git clone https://github.com/<you>/SpendPulse.git
cd SpendPulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --host 127.0.0.1 --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

### Optional: macOS LaunchAgent

```bash
./scripts/install-launch-agent.sh
# restart
launchctl kickstart -k "gui/$(id -u)/com.spendpulse.app"
```

### Optional: household Starbucks reattribution

```bash
cp data/household.example.json data/household.json
# edit cardholder name / store numbers
```

## Upload tips

| Source | Format | Issuer picker |
|--------|--------|----------------|
| Amex statement | PDF | American Express |
| Amex activity export | CSV / Excel | American Express |
| Apple Card | CSV | Apple Card |
| Citi / Chase / Cap One | CSV / Excel | matching issuer |

Pick the issuer, then drop the file. Same issuer + closing month replaces the prior upload.

## Privacy

- Statements live in `data/statements.json` and `data/uploads/`
- No accounts, no cloud sync, no analytics beacons
- Do **not** commit real statement files

## License

MIT — see [LICENSE](LICENSE).
