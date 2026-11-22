# Glasgow Central Mosque – prayer begin times display

A portrait (1080×1920) screen that shows the live time, today's prayer **begin** times,
the next prayer countdown, and the Hijri date, all taken from
[centralmosque.co.uk](https://centralmosque.co.uk/prayer-times/).

## How it works

| Part | What it does |
|---|---|
| `index.html` | The display page. Updates every second, switches day at midnight (UK time), and re-checks the data every 30 minutes. |
| `data/prayer-times.json` | The saved times: about a week back to the end of next month, plus the Hijri date GCM shows each day. |
| `scripts/fetch_times.py` | Downloads the times from the same feed GCM's own website uses and saves them. If the download fails, the old file is kept. |
| `.github/workflows/update-times.yml` | Runs the script automatically just after midnight and at midday, and saves any changes. |
| `assets/*.png` | The five calligraphy tiles. |

Times shown: Fajr, Zuhr, Asr (Asr I, the first Asr time), Maghrib, Isha begin times, plus Sunrise.

## Running the update by hand

On GitHub: **Actions** tab → **Update prayer times** → **Run workflow**.
