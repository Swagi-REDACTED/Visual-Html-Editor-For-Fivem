import webview
import threading
import socket
from contextlib import closing
from api import app, api_instance

def find_free_port():
    """Finds a free port on the local machine."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

if __name__ == '__main__':
    # Find a free port for the Flask server
    port = find_free_port()

    # Run Flask in a separate thread
    flask_thread = threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port, debug=False), daemon=True)
    flask_thread.start()

    # Create the pywebview window
    url = f'http://127.0.0.1:{port}'
    window = webview.create_window('Visual Web Editor', url, js_api=api_instance, width=1920, height=1080)
    
    # Pass the window object to the API class instance
    api_instance.window = window
    
    # Start the pywebview event loop
    webview.start()
