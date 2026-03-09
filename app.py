import sys
import os

# Add your project directory to the Python path
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.append(path)

# Import your bot's Flask app instance
# If your bot doesn't use Flask, you'll need to wrap it
from your_main_bot_file import app  # Replace 'your_main_bot_file' with the actual filename (without .py)
