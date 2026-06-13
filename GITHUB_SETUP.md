# 🚀 Step-by-Step GitHub Upload Instructions

## What is Ready ✅

1. ✅ **`.gitignore` configured**: Safely excludes all secrets and temporary folders.
2. ✅ **`README.md` translated**: Project overview and file description.
3. ✅ **`requirements.txt` added**: Python library dependencies.
4. ✅ **`DEPLOYMENT.md` translated**: Detailed instructions on repository security.
5. ✅ **`env.example` created**: Example configurations template.
6. ✅ **`setup_git.py` provided**: Helper script to configure git config parameters.
7. ✅ **Git repository initialized locally**.
8. ✅ **Submodule/nested git folders ignored**.

---

## Step 1: Configure Git

If you haven't configured your Git credentials, run:
```bash
python setup_git.py
```
This script will configure:
- Your Git user name.
- Your Git email.

---

## Step 2: Create a Repository on GitHub

1. Go to [GitHub.com](https://github.com).
2. Click the green **"New repository"** button.
3. Complete the form:
   - **Repository name**: `BOWTS` (or `BOTS`).
   - **Description**: `Collection of bots and scripts for automation`.
   - **Visibility**: **Public** (or **Private** depending on your choice).
   - **DO NOT check the boxes**:
     - [ ] Add a README file
     - [ ] Add .gitignore
     - [ ] Choose a license
4. Click **"Create repository"**.

---

## Step 3: Link Local Folder to GitHub

Open your terminal and run:
```bash
# Add the remote repository URL
git remote add origin https://github.com/wedybleeno/BOWTS.git

# Set the default branch name to main
git branch -M main

# Upload the project code to GitHub
git push -u origin main
```

---

## Step 4: Verify Ignored Files on GitHub

1. Go to your repository on GitHub.
2. Make sure that the following files **did NOT upload**:
   - `.env`
   - `BOT_TOKEN`
   - `GOOGLE_API_KEY`
   - `user_session.session`
   - `index.db`
   - `result.json`
   - `coins.json`

---

## Step 5: Configure Local Environment Variables

1. Copy the example file to `.env`:
   ```bash
   cp env.example .env
   ```
2. Open `.env` and fill it with your real tokens:
   ```ini
   TELEGRAM_TOKEN=your_bot_token_here
   GOOGLE_API_KEY=your_google_api_key_here
   SOUNDCLOUD_PROFILE_URL=https://soundcloud.com/your-username/likes
   ```

---

## Step 6: Test Bots Locally

Verify that everything works:
```bash
# Test SoundCloud scraper
python soundcloud.py

# Test SoundCloud client_id extractor
python get_client_id.py
```

---

## 🔒 Security Summary

### ✅ Protected Elements:
- All sensitive tokens and keys are listed in `.gitignore`.
- Local variables loaded securely via `dotenv`.

### ⚠️ Review Checklist:
- Double-check that you did not commit credentials in Git history.
- Regularly update Python packages via `requirements.txt`.

---

## 📁 Repository Directory Structure

```
BOWTS/
├── README.md              # Project overview
├── requirements.txt       # Python dependencies
├── DEPLOYMENT.md          # Deployment and security rules
├── GITHUB_SETUP.md        # This step-by-step setup guide
├── env.example            # Template for environment settings
├── setup_git.py           # Git configuration utility
├── .gitignore            # Git exclusions configuration
├── soundcloud.py         # SoundCloud downloader script
├── get_client_id.py      # soundcloud client_id finder script
├── tele.py               # Channel indexing Telegram bot
├── muz*.py               # Music downloader bot scripts
├── cryptobot.py          # Gemini-based Crypto query bot
├── veo.py                # Google Veo video generator bot
├── main6.py              # Main web server
└── ...
```

---

## 🆘 Troubleshooting & Support

### Problem: "Repository not found"
- Verify that your remote URL is correct.
- Check permissions or login.

### Problem: "Authentication failed"
- Create and use a **Personal Access Token (PAT)** classic instead of your account password.
- Run `git push -u origin main` and paste the token when prompted.

### Problem: Exposed Credentials
- If you accidentally upload secrets, run:
  ```bash
  git rm --cached <filename>
  ```
- Make sure to update `.gitignore` and commit again.

---

**🎉 Congratulations! Your clean project is hosted securely on GitHub!**
