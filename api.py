import webview
import json
import traceback
import os
from flask import Flask, request, render_template, send_from_directory
import logging

# Import core logic from other modules
from project_generator import generate_html, generate_lua_script
from html_parser import parse_html_to_project

# --- Suppress Flask's default startup messages for a cleaner console ---
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- Flask App Setup ---
# The 'frontend' directory will serve our static HTML, CSS, and JS files.
app = Flask(__name__, static_folder='frontend', static_url_path='')

class Api:
    """
    The backend API that the pywebview frontend communicates with.
    Handles file dialogs, saving, loading, and importing/exporting projects.
    """
    def __init__(self):
        self.window = None

    def export_html(self, payload):
        """Exports the current project as a single, runnable HTML file."""
        if not self.window:
            return {'status': 'error', 'message': 'Window not available'}
        try:
            file_types = ('HTML File (*.html)',)
            file_path = self.window.create_file_dialog(webview.SAVE_DIALOG, file_types=file_types)
            if file_path:
                # Ensure file_path is a string
                path_to_save = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
                _, full_html = generate_html(payload)
                with open(path_to_save, 'w', encoding='utf-8') as f:
                    f.write(full_html)
                return {'status': 'success', 'message': f'Successfully exported to {os.path.basename(path_to_save)}'}
            return {'status': 'info', 'message': 'Export cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': f'Error exporting: {str(e)}\n{traceback.format_exc()}'}

    def save_lua(self, payload):
        """Exports the current project as a Macho API Lua script."""
        if not self.window:
            return {'status': 'error', 'message': 'Window not available'}
        try:
            file_types = ('Lua Script (*.lua)',)
            file_path = self.window.create_file_dialog(webview.SAVE_DIALOG, file_types=file_types)
            if file_path:
                path_to_save = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
                lua_code = generate_lua_script(payload)
                with open(path_to_save, 'w', encoding='utf-8') as f:
                    f.write(lua_code)
                return {'status': 'success', 'message': f'Successfully saved to {os.path.basename(path_to_save)}'}
            return {'status': 'info', 'message': 'Save cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': f'Error saving Lua: {str(e)}\n{traceback.format_exc()}'}

    def save_project(self, payload):
        """Saves the project state to a JSON file."""
        if not self.window:
            return {'status': 'error', 'message': 'Window not available'}
        try:
            file_types = ('JSON Project (*.json)',)
            file_path = self.window.create_file_dialog(webview.SAVE_DIALOG, file_types=file_types)
            if file_path:
                path_to_save = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
                with open(path_to_save, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, indent=2)
                return {'status': 'success', 'message': f'Project saved to {os.path.basename(path_to_save)}'}
            return {'status': 'info', 'message': 'Save cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': f'Error saving project: {str(e)}'}

    def load_project(self):
        """Loads a project state from a JSON file."""
        if not self.window:
            return {'status': 'error', 'message': 'Window not available'}
        try:
            file_types = ('JSON Project (*.json)',)
            file_path = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
            if file_path:
                path_to_load = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
                with open(path_to_load, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return {'status': 'success', 'data': data}
            return {'status': 'info', 'message': 'Load cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': f'Error loading project: {str(e)}'}

    def import_html(self):
        """Imports an HTML file, parsing its structure, styles, and scripts."""
        if not self.window:
            return {'status': 'error', 'message': 'Window not available'}
        try:
            file_types = ('HTML Files (*.html;*.htm)',)
            file_path = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
            if not file_path:
                return {'status': 'info', 'message': 'Import cancelled.'}

            actual_path = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
            
            with open(actual_path, 'r', encoding='utf-8') as f:
                html_content = f.read()

            project_data = parse_html_to_project(html_content, os.path.dirname(actual_path))
            
            return {'status': 'success', 'data': project_data}
        except Exception as e:
            tb = traceback.format_exc()
            print(f"Error parsing HTML: {e}\n{tb}")
            return {'status': 'error', 'message': f'Error parsing HTML: {str(e)}\n{tb}'}

# Create a single instance of the API
api_instance = Api()

@app.route('/')
def index():
    """Serves the main editor UI."""
    return send_from_directory('frontend', 'index.html')
