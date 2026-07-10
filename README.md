# spendPulse

Most spend trackers stop at “how much did I spend?”  
**spendPulse** answers the questions that actually change behavior:

- How much **coffee** this month — and what’s the annualized pace?
- What’s **avoidable** vs necessary?
- Which **tags** cut across categories (Starbucks, Tesla, Transfers, Company…)?
- Where did **dining** go — by cuisine and distinct restaurants?
- How do **card members** compare month over month?

Local-first. Multi-issuer. Your PDFs and CSV/Excel exports never leave the machine.

<p align="center">
  <img src="https://raw.githubusercontent.com/srinivasgundluri-metropolis/SpendPulse/main/docs/screenshots/01-overview.png" alt="spendPulse overview — coffee and avoidable metrics" width="900" />
</p>

<p align="center"><em>Demo screenshots — names and totals masked.</em></p>

## Why this isn’t another generic tracker

| Generic tracker | spendPulse |
|-----------------|------------|
| One “Food & Drink” bucket | **Coffee** as a first-class metric + visit count + annualized run-rate |
| Flat categories only | **Tags** on every charge — filter the whole dashboard by Starbucks, Tesla, Avoidable, Company… |
| “Discretionary” hand-waving | Explicit **avoidable** rules (dining, sweets, shopping, entertainment, subscriptions, coffee…) |
| Merchant list dump | **Dining** tab: cuisines + distinct restaurants from noisy Amex/Apple strings |
| Single card export | **Cards** filter: one issuer or **all cards clubbed** into one YTD |
| Cloud sync | 100% local — `data/` stays on disk |

## Screenshots

### Overview — coffee & avoidable up front

<img src="https://raw.githubusercontent.com/srinivasgundluri-metropolis/SpendPulse/main/docs/screenshots/01-overview.png" alt="Overview with coffee and avoidable metrics" width="900" />

Net, refunds, **coffee**, **avoidable**, necessary, and company — with MoM when you have prior statements.

### Activity — coffee visits with tags

<img src="https://raw.githubusercontent.com/srinivasgundluri-metropolis/SpendPulse/main/docs/screenshots/02-activity-coffee.png" alt="Coffee activity table with tags" width="900" />

Every coffee charge keeps its category **and** meta tags (`Coffee`, `Starbucks`, `Avoidable`, …).

### Avoidable spend — tagged line by line

<img src="https://raw.githubusercontent.com/srinivasgundluri-metropolis/SpendPulse/main/docs/screenshots/03-activity-avoidable.png" alt="Avoidable spend with tag chips" width="900" />

Not a vague pie slice — a filterable list of what you can actually cut.

### Dining — cuisines & distinct restaurants

<img src="https://raw.githubusercontent.com/srinivasgundluri-metropolis/SpendPulse/main/docs/screenshots/04-dining.png" alt="Dining cuisines breakdown" width="900" />

Noisy statement text collapsed into places you’ve actually been, rolled up by cuisine.

### Tag filter — slice the whole ledger

<img src="https://raw.githubusercontent.com/srinivasgundluri-metropolis/SpendPulse/main/docs/screenshots/05-tag-starbucks.png" alt="Dashboard filtered by Starbucks tag" width="900" />

Pick **Starbucks**, **Tesla**, **Transfers**, or any category tag — Overview, Activity, and YTD all follow.

## Features (full set)

- **Multi-issuer shell** — Amex PDF today; Apple Card / Citi / Chase / Cap One via CSV·Excel activity exports (auto-split by calendar month)
- **Tags & filters** — Member + Tag + Cards + Period
- **Coffee / avoidable / company** metrics and charts
- **Dining** — cuisine + restaurant rollups
- **Transport · Tesla · Transfers** dedicated tabs
- **Members** — share, leaders, MoM
- **macOS LaunchAgent** — keeps the local server up

## Quick start

```bash
git clone https://github.com/srinivasgundluri-metropolis/SpendPulse.git
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
launchctl kickstart -k "gui/$(id -u)/com.spendpulse.app"
```

### Optional: household Starbucks reattribution

```bash
cp data/household.example.json data/household.json
# edit cardholder / store numbers
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
- Do **not** commit real statement files (gitignored)

## License

MIT — see [LICENSE](LICENSE).
