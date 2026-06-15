# Sepolia Daily Mission Runner

Automate your Ethereum Sepolia testnet daily missions — mint, stake, send, and return Plus tokens with an interactive CLI wizard.

## What it does

| Mission | Description |
|---------|-------------|
| **Mint** | Convert USDT→USDT+ or USDC→USDC+ |
| **Stake** | Lock Plus tokens in staking contracts |
| **Send** | Transfer Plus tokens to a target wallet |
| **Receive** | Target wallet receives tokens (completed by Send + Return) |
| **Daily TX** | Filler mint transactions to hit a minimum transaction count |

Check your missions at [testnet.overlayer.fi/early-user](https://testnet.overlayer.fi/early-user).

---

## Quick Start (Termux + Ubuntu)

### 1. Install Termux & Ubuntu

```bash
# Install Termux from: https://f-droid.org/packages/com.termux/

# Inside Termux:
pkg update && pkg upgrade
pkg install proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
```

### 2. Install Python & Git

```bash
apt update && apt install -y python3 python3-pip git
```

### 3. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/sepoliar.git
cd sepoliar
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Set up your wallet

Create `master_privatekey.txt` with your main wallet's private key:

```bash
echo "0xYOUR_PRIVATE_KEY_HERE" > master_privatekey.txt
```

Add your target wallet address to `wallets.txt` (one per line):

```bash
echo "0xYOUR_TARGET_ADDRESS" > wallets.txt
```

> **⚠️ These files are in `.gitignore` and will NEVER be committed.**

### 6. Run the daily mission wizard

```bash
python daily_missions.py
```

The interactive wizard will:
1. Load your wallet & check balances
2. Ask about today's missions (amounts, tokens)
3. Show you an execution plan
4. Ask for confirmation, then run all transactions
5. Optionally verify completion on the Overlayer website

---

## Getting Testnet Tokens

You need testnet ETH + USDT/USDC on Sepolia:

- **ETH**: [Sepolia faucet](https://sepoliafaucet.com/) or [Alchemy faucet](https://sepolia-faucet.alchemy.com/)
- **USDT/USDC**: Available at [testnet.overlayer.fi/early-user](https://testnet.overlayer.fi/early-user)

---

## Project Structure

```
├── daily_missions.py   # Main interactive mission runner (RECOMMENDED)
├── mission_runner.py   # Alternative runner with --auto / --dry-run modes
├── auto_mint.py        # Standalone mint script (USDT→USDT+ or USDC→USDC+)
├── stake.py            # Standalone staking script
├── run_all.py          # Legacy all-in-one runner (interactive + auto)
├── quick_transfer_usdc.py  # Quick USDC+ transfer (CLI args)
├── config.py           # Wallet & config loading
├── contract_encoder.py # ABI encoding helpers
├── utils/
│   ├── crypto.py       # Keccak-256, secp256k1 signing
│   ├── rpc.py          # JSON-RPC calls, gas estimation, tx broadcasting
│   ├── display.py      # Terminal colors & logging
│   ├── proxy.py        # Proxy resolution (http/socks5)
│   └── messages.py     # Error message helpers
└── requirements.txt    # Python dependencies (requests, python-dotenv)
```

## Modes

### Interactive (daily_missions.py)
```bash
python daily_missions.py
```
Full wizard — guides you through every step.

### Auto mode (mission_runner.py)
```bash
python mission_runner.py --auto
```
Reads `missions.json` and runs without prompts. Supports `--dry-run` to preview.

Example `missions.json`:
```json
{
  "missions": [
    {"type": "mint",   "token": "usdt", "amount": 227},
    {"type": "stake",  "token": "usdc", "amount": 447},
    {"type": "send",   "token": "usdc", "amount": 250},
    {"type": "daily_tx", "min_count": 11}
  ],
  "settings": {
    "mint_per_tx": 100,
    "delay_min": 5,
    "delay_max": 12
  }
}
```

> **Tip:** Use `daily_missions.py` for the interactive wizard — no JSON editing needed.

### Standalone scripts
```bash
python auto_mint.py --token usdc --count 5 --amount 100 --yes
python stake.py --amount 444 --token usdt --yes
```

---

## Configuration

All scripts read wallets from:
- `master_privatekey.txt` — main wallet private key
- `wallets.txt` — target wallet addresses (one per line, or `address:private_key` pairs)

Optionally set via environment variables:
- `FUNDING_PRIVATE_KEY=0x...` — override main wallet key
- `MINT_TARGET`, `STAKE_TARGET`, `SEND_TARGET`, `MIN_TX` — auto-mode amounts

---

## Safety

- Private keys are NEVER hardcoded in any `.py` file
- `master_privatekey.txt` and `wallets.txt` are gitignored
- All transactions run on **Sepolia Testnet** — no real funds at risk
