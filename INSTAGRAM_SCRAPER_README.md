# Instagram Scraper with Playwright

A robust Instagram scraper built with Playwright that handles login, cookie management, and provides stealth features to avoid detection.

## Features

- ✅ **Secure Login**: Handles Instagram login with username/password
- 🍪 **Cookie Management**: Automatically saves and reuses cookies (filename: `{username}.json`)
- 🥷 **Stealth Mode**: Advanced anti-detection features
- 🔄 **Retry Logic**: Robust error handling and retry mechanisms
- 📝 **Comprehensive Logging**: Detailed logging for debugging
- 🌐 **Proxy Support**: Optional proxy configuration
- 🎯 **Context Manager**: Clean resource management

## Installation

1. Install required dependencies:
```bash
pip install playwright python-dotenv
playwright install chromium
```

2. Set up environment variables in `.env` file:
```env
INSTAGRAM_USERNAME=your_username_or_email
INSTAGRAM_PASSWORD=your_password
PROXY=host:port  # Optional
```

## Usage

### Basic Usage

```python
from src.ig_scrapper import InstagramScraper

# Using context manager (recommended)
with InstagramScraper() as scraper:
    if scraper.login("your_username", "your_password"):
        print("Login successful!")
        # Your scraping code here
```

### Advanced Usage

```python
import os
from dotenv import load_dotenv
from src.ig_scrapper import InstagramScraper

load_dotenv()

username = os.getenv("INSTAGRAM_USERNAME")
password = os.getenv("INSTAGRAM_PASSWORD")

with InstagramScraper(cookies_dir="my_cookies") as scraper:
    # Login with cookie reuse
    if scraper.login(username, password, use_saved_cookies=True):
        # Get user info
        user_info = scraper.get_current_user_info()
        print(f"User info: {user_info}")
        
        # Navigate to any Instagram page
        scraper.page.goto("https://www.instagram.com/explore/")
```

### Running the Example

```bash
# Basic example
python example_ig_scraper.py

# Test cookie management
python example_ig_scraper.py test-cookies
```

## Cookie Management

The scraper automatically manages cookies:

- **Save Location**: `cookies/{username}.json`
- **Auto-reuse**: Loads saved cookies on subsequent logins
- **Fallback**: Falls back to fresh login if cookies are expired
- **Format**: JSON with timestamp and cookie data

Example cookie file structure:
```json
{
  "username": "your_username",
  "timestamp": 1703123456.789,
  "cookies": [
    {
      "name": "sessionid",
      "value": "abc123...",
      "domain": ".instagram.com",
      "path": "/",
      "expires": 1703209856.789,
      "httpOnly": true,
      "secure": true
    }
  ]
}
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `INSTAGRAM_USERNAME` | Instagram username or email | Yes |
| `INSTAGRAM_PASSWORD` | Instagram password | Yes |
| `PROXY` | Proxy configuration (host:port or user:pass@host:port) | No |

### Browser Settings

The scraper uses optimized browser settings:

- **User Agent**: Realistic Chrome user agent
- **Viewport**: 1366x768 (common resolution)
- **Stealth Features**: Removes automation indicators
- **Headers**: Realistic HTTP headers
- **Timeouts**: Optimized for Instagram's response times

## Error Handling

The scraper includes comprehensive error handling:

- **Login Errors**: Detects and reports login failures
- **Network Issues**: Handles timeouts and connection problems
- **Element Detection**: Graceful handling of missing elements
- **Cookie Issues**: Automatic fallback to fresh login

## Logging

Logs are written to:
- **Console**: Real-time feedback
- **File**: `ig_scraper_logs.log` (main scraper)
- **File**: `example_ig_scraper.log` (example script)

Log levels:
- `INFO`: General information
- `WARNING`: Non-critical issues
- `ERROR`: Critical errors
- `DEBUG`: Detailed debugging info

## Security Considerations

- **Credentials**: Store credentials in environment variables, never in code
- **Cookies**: Cookie files contain sensitive session data
- **Rate Limiting**: Instagram may rate limit or block automated access
- **Terms of Service**: Ensure compliance with Instagram's ToS

## Troubleshooting

### Common Issues

1. **Login Failed**
   - Verify credentials are correct
   - Check if Instagram requires 2FA
   - Try disabling headless mode for manual verification

2. **Cookies Not Working**
   - Delete old cookie files and try fresh login
   - Check if Instagram changed their authentication

3. **Detection Issues**
   - Use proxy if available
   - Add random delays between actions
   - Ensure browser is up to date

### Debug Mode

Enable debug logging:
```python
import logging
logging.getLogger().setLevel(logging.DEBUG)
```

## API Reference

### InstagramScraper Class

#### `__init__(cookies_dir="cookies")`
Initialize the scraper with optional custom cookies directory.

#### `login(username, password, use_saved_cookies=True)`
Login to Instagram with optional cookie reuse.

**Parameters:**
- `username` (str): Instagram username or email
- `password` (str): Instagram password
- `use_saved_cookies` (bool): Whether to try saved cookies first

**Returns:** `bool` - True if login successful

#### `get_current_user_info()`
Get information about the currently logged-in user.

**Returns:** `dict` - User information or None

#### `cleanup()`
Clean up browser resources (automatically called by context manager).

## Contributing

1. Follow the existing code style
2. Add comprehensive error handling
3. Include logging for debugging
4. Test with different Instagram accounts
5. Update documentation for new features

## License

This project is for educational purposes only. Please respect Instagram's Terms of Service and use responsibly.
