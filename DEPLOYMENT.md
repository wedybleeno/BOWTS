# 🚀 Deployment Instructions for GitHub

## Step 1: Prepare for Upload

### 1.1 Initialize Git Repository
```bash
# Initialize a Git repository
git init

# Add all files (excluding files matched in .gitignore)
git add .

# Create the initial commit
git commit -m "Initial commit: BOTS collection"
```

### 1.2 Verify Ignored Files
Make sure that your private, sensitive credentials will not be committed to GitHub. The following files should not be uploaded:
- `.env`
- `BOT_TOKEN`
- `GOOGLE_API_KEY`
- `user_session.session`
- `index.db`
- `result.json`
- `coins.json`

Verify these patterns in `.gitignore`.

---

## Step 2: Create a Private Repository on GitHub

### 2.1 Create Repository
1. Navigate to [GitHub.com](https://github.com)
2. Click "New repository"
3. Enter name: `BOTS`
4. **IMPORTANT**: Choose "Private" (to keep your repo closed to third parties)
5. Do NOT check the boxes for README, .gitignore, or license.
6. Click "Create repository"

### 2.2 Link Local Repository to GitHub
```bash
# Add remote origin URL (replace YOUR_USERNAME with your GitHub login)
git remote add origin https://github.com/YOUR_USERNAME/BOTS.git

# Rename default branch to main (modern standard)
git branch -M main

# Push the code to GitHub
git push -u origin main
```

---

## Step 3: Setup Security

### 3.1 Create Environment Variable File
Create a `.env` file (which is ignored by Git):
```env
# Telegram Bot Token
TELEGRAM_TOKEN=your_telegram_bot_token_here

# Google API Key
GOOGLE_API_KEY=your_google_api_key_here

# SoundCloud Profile URL
SOUNDCLOUD_PROFILE_URL=https://soundcloud.com/your-username/likes
```

### 3.2 Configure GitHub Secrets (Optional)
If you plan to use GitHub Actions:

1. Navigate to Settings → Secrets and variables → Actions.
2. Add secrets:
   - `TELEGRAM_TOKEN`
   - `GOOGLE_API_KEY`

---

## Step 4: Verify Upload

### 4.1 Verify Files on GitHub
1. Go to your repository on GitHub.
2. Check that all source code files have been uploaded.
3. Verify that your sensitive files (e.g. `.env`, database files) are NOT uploaded.

### 4.2 Verify Privacy Settings
1. Open your repository URL in an incognito/private browser tab.
2. Ensure you get a 404 (Not Found) error, verifying that the repository is indeed private.

---

## Step 5: Advanced Branch Management (Optional)

### 5.1 Develop Branch Setup
```bash
# Create a development branch
git checkout -b develop

# Push the develop branch to GitHub
git push -u origin develop
```

### 5.2 Branch Protection Rules (Optional)
1. Go to Settings → Branches.
2. Add a protection rule for the `main` branch.
3. Enable "Require pull request reviews before merging".

---

## Step 6: Clone on Other Devices

### 6.1 Clone Repository
```bash
# Clone the private repository
git clone https://github.com/YOUR_USERNAME/BOTS.git

# Change directory to project folder
cd BOTS

# Install requirements
pip install -r requirements.txt

# Create .env file from example
cp env.example .env
# Edit the .env file with your tokens and keys
```

---

## 🔒 Crucial Security Reminders

1. **Never commit raw tokens or API keys to the repository.**
2. **Always use `.env` files for managing credentials locally.**
3. **Regularly update dependencies via requirements.**
4. **Use private repositories for personal projects with sensitive APIs.**

---

## 📞 Support & Troubleshooting

If you encounter issues:
1. Double-check your `.gitignore` configuration.
2. Verify repository visibility status (Private).
3. Check your authentication permissions on GitHub.
