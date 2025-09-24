
Trailing Stop (paper) on Alpaca via GitHub Actions

Setup
	1.	Create a private repo.
	2.	Upload these 4 files.
	3.	Go to Settings → Secrets and variables → Actions → “New repository secret”:
	•	APCA_API_KEY_ID = your key (paper)
	•	APCA_API_SECRET_KEY = your secret (paper)

Execution
	•	Manual: Actions → trailing-stop-paper → Run workflow.
	•	(Optional) Automatic: uncomment the schedule block in .github/workflows/run.yml and commit.

What it does
	•	Reads all your open paper positions.
	•	If a position has a gain ≥ 5%, it creates a SELL trailing_stop GTC order with trail_percent = 8.
	•	Prevents duplicate trailing stops for the same symbol.
	•	Prints in the logs what it sent and what it skipped.

Notes
	•	It only closes long positions. For shorts, adapt side=BUY and adjust the logic as needed.
	•	The trailing stop is triggered only during regular market hours; once triggered, it executes as a market order.
