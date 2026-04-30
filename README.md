# AIREP
Investor Sentiment and Bitcoin Asset Pricing

## Data Collection

Daily automated collection of Bitcoin market data and sentiment indicators.

### Sources

| Data | Source | API |
|------|--------|-----|
| BTC Price (OHLCV) | CoinGecko | Free, no key |
| Fear & Greed Index | Alternative.me | Free, no key |
| Market Sentiment (Sentix proxy) | CoinGecko Global | Free, no key |
| Google Trends | Google Trends | via pytrends |

### Setup

```bash
pip install -r requirements.txt
```

### Usage

```bash
# Run all collectors once
python collect.py

# Run on daily schedule (00:05 UTC)
python collect.py --schedule

# Run individual collectors
python collect.py --price
python collect.py --sentiment
python collect.py --trends
```

### Output

CSV files are written to `data/`:
- `btc_price.csv` — daily price, market cap, volume, OHLC
- `fear_greed.csv` — Fear & Greed index, BTC dominance, sentiment proxy
- `google_trends.csv` — search interest for Bitcoin-related keywords
