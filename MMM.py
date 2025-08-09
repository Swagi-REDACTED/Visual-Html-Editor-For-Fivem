import webview
import json
import os
import threading
from flask import Flask, render_template_string, request
import sys
import logging
import re
import socket
from contextlib import closing
from bs4 import BeautifulSoup, NavigableString
import traceback

# --- Suppress Flask's default startup messages for a cleaner console ---
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- Flask App Setup ---
app = Flask(__name__)

# --- HTML/LUA Generation and Parsing ---

def generate_html(components, custom_css, custom_js_map):
    """Generates a complete, runnable HTML file from the component structure."""
    def style_to_css(style_obj):
        css_rules = []
        for key, value in style_obj.items():
            prop = re.sub(r'(?<!^)(?=[A-Z])', '-', key).lower()
            if value:
                css_rules.append(f"{prop}: {value};")
        return " ".join(css_rules)

    body_elements = []
    scripts = []
    sorted_components = sorted(components, key=lambda c: int(c.get('style', {}).get('zIndex', 0)))

    for comp in sorted_components:
        comp_style = comp.get('style', {})
        inline_style = style_to_css(comp_style)
        
        if comp.get('id') in custom_js_map and custom_js_map[comp['id']]:
            script_content = f"""
            try {{
                const el = document.getElementById('{comp["id"]}');
                if(el) {{ {custom_js_map[comp['id']]} }}
            }} catch (e) {{ console.error("Error in custom script for {comp['id']}:", e); }}
            """
            scripts.append(script_content)

        tag = comp.get('tag', 'div')
        
        children_html = ""
        if 'children' in comp and comp['children']:
            children_html = generate_html(comp['children'], "", {})[0]

        text_content = comp.get('text', '')
        
        attributes = f'id="{comp["id"]}" style="{inline_style}"'
        if comp.get('attributes'):
            for key, value in comp['attributes'].items():
                # Join list values for attributes like 'class'
                if isinstance(value, list):
                    attributes += f' {key}="{" ".join(value)}"'
                else:
                    attributes += f' {key}="{value}"'

        if tag in ['svg', 'path', 'g']:
             body_elements.append(f'<{tag} {attributes}>{children_html}</{tag}>')
        else:
             body_elements.append(f'<{tag} {attributes}>{text_content}{children_html}</{tag}>')


    body_html = "\n".join(body_elements)
    script_html = "\n".join(scripts)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Exported Page</title>
    <style>
        body {{ margin: 0; padding: 0; font-family: sans-serif; }}
        {custom_css}
    </style>
</head>
<body>
    {body_html}
    <script>
        document.addEventListener('DOMContentLoaded', () => {{
            {script_html}
        }});
    </script>
</body>
</html>"""
    return body_html, html_template

def generate_lua_script(project_data):
    """Generates a runnable Macho API Lua script from the project data."""
    components = project_data.get('components', [])
    custom_css = project_data.get('css', '')
    custom_js_map = project_data.get('js', {})
    global_settings = project_data.get('globalSettings', {})

    body_html, _ = generate_html(components, "", {})
    
    # Use long strings for HTML and CSS to avoid escaping issues
    sanitized_html = body_html
    sanitized_css = custom_css

    interaction_js = """
        const elementVisibility = {};

        function toggleElementVisibility(elementId) {
            const el = document.getElementById(elementId);
            if (!el) return;
            
            if (elementVisibility[elementId] === undefined) {
                elementVisibility[elementId] = getComputedStyle(el).display !== 'none';
            }
            
            elementVisibility[elementId] = !elementVisibility[elementId];
            el.style.display = elementVisibility[elementId] ? '' : 'none';
        }

        window.addEventListener("message", (event) => {
            const data = event.data;
            if (data.action === 'toggle') {
                toggleElementVisibility(data.id);
            }
        });
    """
    
    all_js = interaction_js
    for comp_id, script in custom_js_map.items():
        all_js += f"try {{ const el = document.getElementById('{comp_id}'); if(el) {{ {script} }} }} catch(e) {{ console.error(e); }}\\n"

    # Decide string literal type for JS messages
    def sanitize_js_for_lua(js_string):
        if "'" not in js_string:
            return f"'{js_string}'"
        elif '"' not in js_string:
            return f'"{js_string}"'
        else:
            return f"[=[{js_string}]=]"

    key_handlers = []
    master_key = global_settings.get('masterKey')
    if master_key:
        key_handlers.append(f"if key == {master_key} then")
        for comp in components:
            interaction = comp.get('interaction', {})
            if interaction.get('useMasterKey'):
                js_message = f"window.postMessage({{ action = 'toggle', id = '{comp['id']}' }})"
                key_handlers.append(f"    MachoInjectJavaScript({sanitize_js_for_lua(js_message)})")
        key_handlers.append("end")

    for comp in components:
        interaction = comp.get('interaction', {})
        open_key = interaction.get('openKey')
        if open_key and not interaction.get('useMasterKey'):
            js_message = f"window.postMessage({{ action = 'toggle', id = '{comp['id']}' }})"
            key_handlers.append(f"if key == {open_key} then")
            key_handlers.append(f"    MachoInjectJavaScript({sanitize_js_for_lua(js_message)})")
            key_handlers.append("end")
            
    key_handler_code = "\n    ".join(key_handlers)

    lua_script = f"""-- Generated by Visual Web Editor
local ui_html = [=[{sanitized_html}]=]
local ui_css = [=[{sanitized_css}]=]
local ui_js = [=[{all_js}]=]

Citizen.CreateThread(function()
    MachoInjectJavaScript([=[
        document.head.innerHTML = `<style>${{ui_css}}</style>`;
        document.body.innerHTML = `${{ui_html}}`;
        const scriptTag = document.createElement('script');
        scriptTag.type = 'text/javascript';
        scriptTag.innerHTML = `{all_js}`;
        document.body.appendChild(scriptTag);
    ]=])
end)

MachoOnKeyUp(function(key)
    {key_handler_code}
end)

print("Macho DUI script loaded.")
"""
    return lua_script


def css_to_json(css_string):
    style_json = {}
    if not css_string: return style_json
    rules = css_string.split(';')
    for rule in rules:
        if ':' in rule:
            key, value = rule.split(':', 1)
            key_parts = key.strip().split('-')
            camel_key = key_parts[0] + ''.join(p.capitalize() for p in key_parts[1:])
            style_json[camel_key] = value.strip()
    return style_json

def parse_html_element(element, next_id_func):
    if not hasattr(element, 'name') or not element.name:
        return None

    comp_id = element.get('id', f"element-{next_id_func()}")
    tag = element.name

    type_map = {'div': 'div', 'header': 'header', 'footer': 'footer', 'p': 'text', 'button': 'button', 'main': 'content', 'svg': 'div', 'g': 'div', 'path': 'div'}
    comp_type = type_map.get(tag, 'div')

    component = {
        'id': comp_id,
        'type': comp_type,
        'tag': tag,
        'name': f"{comp_id}",
        'children': [],
        'style': css_to_json(element.get('style', '')),
        'text': '',
        'attributes': {k: v for k, v in element.attrs.items() if k not in ['id', 'style']}
    }

    text_content = []
    for content in element.contents:
        if isinstance(content, NavigableString) and content.strip():
            text_content.append(content.strip())
        elif hasattr(content, 'name') and content.name:
            child_comp = parse_html_element(content, next_id_func)
            if child_comp:
                component['children'].append(child_comp)
    
    if text_content:
        component['text'] = ' '.join(text_content)

    return component

# --- HTML Template for the Editor Frontend ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Visual Web Editor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
    <style>
        :root { --bg-primary: #1a1a1a; --bg-secondary: #2a2d32; --bg-tertiary: #3a3d42; --text-primary: #f0f0f0; --accent: #3b82f6; }
        body { font-family: 'Inter', sans-serif; background-color: var(--bg-primary); color: var(--text-primary); overflow: hidden; }
        
        #main-layout { display: grid; height: 100vh; width: 100vw; grid-template-rows: auto 1fr; grid-template-columns: 224px 5px 288px 5px 1fr 5px 384px; }
        .panel { background-color: #202327; overflow: hidden; }
        #top-toolbar { grid-column: 1 / -1; background-color: var(--bg-secondary); }
        #elements-panel { grid-area: 2 / 1 / 3 / 2; }
        .resizer-v { cursor: col-resize; background-color: var(--bg-tertiary); }
        .resizer-h { cursor: row-resize; background-color: var(--bg-tertiary); }
        #hierarchy-panel-container { grid-area: 2 / 3 / 3 / 4; }
        #canvas-section { grid-area: 2 / 5 / 3 / 6; display: grid; grid-template-rows: 1fr 5px 33%; }
        #canvas-wrapper { grid-row: 1 / 2; }
        #bottom-editors { grid-row: 3 / 4; }
        #properties-panel-container { grid-area: 2 / 7 / 3 / 8; }

        #canvas {
            background-color: #111;
            background-image: linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px);
            background-size: 20px 20px; border: 1px solid #444; position: relative;
        }
        .component-wrapper { position: absolute; border: 1px dashed transparent; transition: border-color 0.2s; }
        .component-wrapper:hover { border-color: var(--accent); }
        .component-wrapper.selected { border: 2px solid var(--accent) !important; z-index: 1000 !important; }
        .resizer { position: absolute; width: 10px; height: 10px; background: var(--accent); border: 1px solid white; border-radius: 50%; z-index: 1001; }
        .resizer.br { bottom: -5px; right: -5px; cursor: se-resize; }
        #hierarchy-panel ul { padding-left: 15px; border-left: 1px solid #444; }
        #hierarchy-panel li { padding: 4px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; }
        #hierarchy-panel .component-item:hover { background-color: var(--bg-tertiary); }
        #hierarchy-panel .component-item.selected { background-color: var(--accent); color: white; }
        .hierarchy-children { margin-top: 4px; }
        #properties-panel input, #properties-panel textarea, #properties-panel select { background-color: #4a4d52; border: 1px solid #666; border-radius: 4px; padding: 4px 8px; width: 100%; }
        #properties-panel label { font-weight: 500; margin-top: 8px; display: block; }
        #context-menu { position: absolute; background-color: var(--bg-secondary); border: 1px solid #555; border-radius: 5px; padding: 5px; z-index: 2000; display: none; }
        #context-menu div { padding: 8px 12px; cursor: pointer; }
        #context-menu div:hover { background-color: var(--accent); }
        .prop-group summary { font-size: 1.125rem; font-weight: 600; margin-top: 1rem; border-bottom: 1px solid var(--bg-tertiary); padding-bottom: 0.25rem; cursor: pointer; }
    </style>
</head>
<body class="text-sm">
    <div id="main-layout">
        <!-- Top Toolbar -->
        <div id="top-toolbar" class="p-2 flex items-center space-x-4">
            <h1 class="text-lg font-bold text-white">Visual Editor</h1>
            <div class="flex items-center space-x-2">
                <button id="toggle-elements" class="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded" title="Toggle Elements Panel"><i class="fas fa-bars"></i></button>
                <button id="toggle-hierarchy" class="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded" title="Toggle Hierarchy Panel"><i class="fas fa-sitemap"></i></button>
                <button id="toggle-properties" class="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded" title="Toggle Properties Panel"><i class="fas fa-sliders-h"></i></button>
            </div>
             <div class="flex items-center space-x-2 ml-auto">
                <label for="master-key" class="text-white">Master Key:</label>
                <input type="text" id="master-key" class="bg-gray-900 text-white w-24 p-1 rounded" placeholder="e.g., 0x78">
            </div>
        </div>

        <!-- Elements Panel -->
        <div id="elements-panel" class="panel p-4 flex flex-col text-white overflow-y-auto">
            <h2 class="text-xl font-bold mb-4">Elements</h2>
            <div id="toolbar" class="space-y-2">
                <h3 class="font-bold mt-4 border-b border-gray-600 pb-1">Containers</h3>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="header"><i class="fas fa-window-maximize mr-2"></i> Header</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="content"><i class="fas fa-align-justify mr-2"></i> Content</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="footer"><i class="fas fa-shoe-prints mr-2"></i> Footer</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="div"><i class="fas fa-square-full mr-2"></i> Div</div>
                <h3 class="font-bold mt-4 border-b border-gray-600 pb-1">Widgets</h3>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="text"><i class="fas fa-font mr-2"></i> Text</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="button"><i class="fas fa-mouse-pointer mr-2"></i> Button</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="checkbox"><i class="fas fa-check-square mr-2"></i> Checkbox</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="slider"><i class="fas fa-sliders-h mr-2"></i> Slider</div>
                <div class="p-2 bg-gray-700 rounded cursor-pointer" draggable="true" data-type="customWidget"><i class="fas fa-puzzle-piece mr-2"></i> Custom Widget</div>
            </div>
            <div class="mt-auto pt-4 space-y-2">
                <button id="import-btn" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-2 px-4 rounded"><i class="fas fa-file-import mr-2"></i> Import HTML</button>
                <button id="export-btn" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"><i class="fas fa-file-export mr-2"></i> Export to HTML</button>
                <button id="save-lua-btn" class="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-4 rounded"><i class="fas fa-save mr-2"></i> Save to Lua</button>
                <button id="load-btn" class="w-full bg-yellow-600 hover:bg-yellow-700 text-white font-bold py-2 px-4 rounded"><i class="fas fa-folder-open mr-2"></i> Load Project</button>
            </div>
        </div>
        <div id="resizer-v1" class="resizer-v" style="grid-area: 2 / 2 / 3 / 3;"></div>
        <div id="hierarchy-panel-container" class="panel p-4 flex flex-col text-white">
            <h2 class="text-xl font-bold mb-4">Hierarchy</h2>
            <div id="hierarchy-panel" class="flex-1 overflow-y-auto"></div>
        </div>
        <div id="resizer-v2" class="resizer-v" style="grid-area: 2 / 4 / 3 / 5;"></div>
        <div id="canvas-section" class="panel">
            <div id="canvas-wrapper" class="p-4 overflow-auto">
                <div id="canvas" class="h-full w-full"></div>
            </div>
            <div id="resizer-h1" class="resizer-h" style="grid-row: 2 / 3;"></div>
            <div id="bottom-editors" class="p-2 flex flex-col">
                <h3 class="text-lg font-semibold mb-2 text-white">Global CSS & Element JS</h3>
                <div class="flex-1 grid grid-cols-2 gap-2">
                    <textarea id="global-css" class="w-full h-full bg-gray-900 text-green-300 font-mono" placeholder="Enter custom CSS and @keyframes here..."></textarea>
                    <textarea id="element-js" class="w-full h-full bg-gray-900 text-yellow-300 font-mono" placeholder="Enter custom JavaScript for the selected element here... (use 'el' to reference the element)"></textarea>
                </div>
            </div>
        </div>
        <div id="resizer-v3" class="resizer-v" style="grid-area: 2 / 6 / 3 / 7;"></div>
        <div id="properties-panel-container" class="panel p-4 flex flex-col">
            <h2 class="text-xl font-bold mb-4 text-white">Properties</h2>
            <div id="properties-panel" class="space-y-1 overflow-y-auto">
                <p class="text-gray-400">Select an element to edit.</p>
            </div>
        </div>
    </div>
    
    <div id="context-menu"></div>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            const canvas = document.getElementById('canvas');
            const toolbar = document.getElementById('toolbar');
            const hierarchyPanel = document.getElementById('hierarchy-panel');
            const propertiesPanel = document.getElementById('properties-panel');
            const contextMenu = document.getElementById('context-menu');
            const globalCssEditor = document.getElementById('global-css');
            const elementJsEditor = document.getElementById('element-js');
            const importBtn = document.getElementById('import-btn');
            const saveLuaBtn = document.getElementById('save-lua-btn');
            const loadBtn = document.getElementById('load-btn');
            const exportBtn = document.getElementById('export-btn');

            let components = [];
            let customJsMap = {};
            let selectedComponentId = null;
            let nextId = 1;
            let globalSettings = { masterKey: '' };

            const WIDGET_TYPES = ['text', 'button', 'checkbox', 'slider', 'customWidget'];

            function getNewId() { return `element-${nextId++}`; }
            function findComponent(id, comps = components) { for (const comp of comps) { if (comp.id === id) return comp; if (comp.children) { const found = findComponent(id, comp.children); if (found) return found; } } return null; }
            function findParent(childId, comps = components, parent = null) { for (const comp of comps) { if (comp.id === childId) return parent; if (comp.children) { const found = findParent(childId, comp.children, comp); if (found) return found; } } return null; }

            function createComponent(type, parentId = null) {
                const id = getNewId();
                let newComp = { id, type, tag: type, name: `${type}-${id.split('-')[1]}`, children: [], style: { position: 'absolute', left: '50px', top: '50px', width: '200px', height: '100px', backgroundColor: '#555', border: '1px solid #888', borderRadius: '5px', padding: '10px', boxSizing: 'border-box', zIndex: components.length + 1 } };
                switch (type) {
                    case 'text': newComp.tag = 'p'; newComp.text = 'Editable Text'; newComp.style = { ...newComp.style, height: 'auto', backgroundColor: 'transparent', border: 'none', color: '#ffffff' }; break;
                    case 'button': newComp.tag = 'button'; newComp.text = 'Button'; newComp.style = { ...newComp.style, width: '120px', height: '40px', textAlign: 'center', cursor: 'pointer', display: 'grid', placeItems: 'center' }; break;
                    case 'checkbox': newComp.label = 'Checkbox'; newComp.checked = false; newComp.style = { ...newComp.style, width: 'auto', height: 'auto', backgroundColor: 'transparent', border: 'none', display: 'flex', alignItems: 'center' }; break;
                    case 'slider': newComp.min = 0; newComp.max = 100; newComp.value = 50; newComp.style = { ...newComp.style, height: '20px' }; break;
                    case 'header': newComp.tag = 'header'; newComp.style = { ...newComp.style, height: '150px', width: '100%', left: '0px', top: '0px', borderRadius: '0px' }; break;
                    case 'content': newComp.tag = 'main'; break;
                    case 'footer': newComp.tag = 'footer'; break;
                    case 'customWidget': newComp.style.border = '2px dashed #00ffff'; break;
                }
                const parent = parentId ? findComponent(parentId) : null;
                if (WIDGET_TYPES.includes(type) && (!parent || !['content', 'div', 'header', 'footer'].includes(parent.type))) { alert('Widgets can only be added inside a container.'); return; }
                if (parent) { parent.children.push(newComp); newComp.style.left = '10px'; newComp.style.top = '10px'; } else { components.push(newComp); }
                renderAll();
                selectComponent(id);
            }

            function renderAll() {
                const scrollState = {
                    hierarchy: hierarchyPanel.scrollTop,
                    properties: propertiesPanel.parentElement.scrollTop
                };
                canvas.innerHTML = '';
                hierarchyPanel.innerHTML = '';
                const hierarchyRoot = document.createElement('ul');
                components.sort((a, b) => (a.style.zIndex || 0) - (b.style.zIndex || 0)).forEach(comp => { renderComponentOnCanvas(comp); hierarchyRoot.appendChild(renderComponentInHierarchy(comp)); });
                hierarchyPanel.appendChild(hierarchyRoot);
                updatePropertiesPanel();
                
                hierarchyPanel.scrollTop = scrollState.hierarchy;
                propertiesPanel.parentElement.scrollTop = scrollState.properties;
            }
            
            function renderComponentOnCanvas(component, parentElement = canvas) {
                const wrapper = document.createElement(component.tag || 'div');
                wrapper.className = 'component-wrapper';
                wrapper.id = component.id; // Use the component's actual ID
                if (selectedComponentId === component.id) wrapper.classList.add('selected');
                wrapper.dataset.id = component.id; // Keep data-id for selection logic
                Object.keys(component.style).forEach(key => { wrapper.style[key] = component.style[key]; });
                
                // Set non-style attributes
                if(component.attributes) {
                    Object.keys(component.attributes).forEach(key => {
                        wrapper.setAttribute(key, component.attributes[key]);
                    });
                }

                if (component.text) {
                    wrapper.textContent = component.text;
                }

                if(selectedComponentId === component.id){ const resizer = document.createElement('div'); resizer.className = 'resizer br'; wrapper.appendChild(resizer); addResizerListeners(resizer, wrapper, component); }
                parentElement.appendChild(wrapper);
                addDragListeners(wrapper, component);
                if (component.children) { component.children.forEach(child => renderComponentOnCanvas(child, wrapper)); }
            }
            
            function renderComponentInHierarchy(component) {
                const li = document.createElement('li');
                li.className = `component-item ${component.type}`;
                if (selectedComponentId === component.id) li.classList.add('selected');
                li.dataset.id = component.id;
                li.draggable = true;
                const ICONS = { header: 'fa-window-maximize', content: 'fa-align-justify', footer: 'fa-shoe-prints', div: 'fa-square-full', text: 'fa-font', button: 'fa-mouse-pointer', checkbox: 'fa-check-square', slider: 'fa-sliders-h', customWidget: 'fa-puzzle-piece' };
                li.innerHTML = `<i class="fas ${ICONS[component.type]} mr-2 w-4"></i><span>${component.name}</span>`;
                li.addEventListener('click', e => { e.stopPropagation(); selectComponent(component.id); });
                li.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); showContextMenu(e, component.id); });
                addHierarchyDragListeners(li, component);
                if (component.children && component.children.length > 0) { const childrenUl = document.createElement('ul'); childrenUl.className = 'hierarchy-children'; component.children.forEach(child => childrenUl.appendChild(renderComponentInHierarchy(child))); li.appendChild(childrenUl); }
                return li;
            }

            function selectComponent(id) {
                if (selectedComponentId === id) return;
                
                if (selectedComponentId) {
                    const oldWrapper = canvas.querySelector(`.component-wrapper[data-id="${selectedComponentId}"]`);
                    const oldHierarchyItem = hierarchyPanel.querySelector(`.component-item[data-id="${selectedComponentId}"]`);
                    if (oldWrapper) oldWrapper.classList.remove('selected');
                    if (oldHierarchyItem) oldHierarchyItem.classList.remove('selected');
                }
                
                selectedComponentId = id;

                if (id) {
                    const newWrapper = canvas.querySelector(`.component-wrapper[data-id="${id}"]`);
                    const newHierarchyItem = hierarchyPanel.querySelector(`.component-item[data-id="${id}"]`);
                    if (newWrapper) newWrapper.classList.add('selected');
                    if (newHierarchyItem) newHierarchyItem.classList.add('selected');
                    elementJsEditor.value = customJsMap[id] || '';
                } else {
                    elementJsEditor.value = '';
                }
                
                updatePropertiesPanel();
            }

            function parseBorderRadius(radiusString) {
                if (!radiusString || typeof radiusString !== 'string') return ['','','',''];
                const parts = radiusString.split(' ').filter(p => p);
                if (parts.length === 1) return [parts[0], parts[0], parts[0], parts[0]];
                if (parts.length === 2) return [parts[0], parts[1], parts[0], parts[1]];
                if (parts.length === 3) return [parts[0], parts[1], parts[2], parts[1]];
                if (parts.length >= 4) return [parts[0], parts[1], parts[2], parts[3]];
                return ['','','',''];
            }

            function updatePropertiesPanel() {
                const component = findComponent(selectedComponentId);
                if (!component) { propertiesPanel.innerHTML = '<p class="text-gray-400">Select an element to edit.</p>'; return; }
                let specificProps = '';
                switch(component.type) {
                    case 'text': specificProps = `<div><label>Text Content</label><textarea data-prop="text">${component.text || ''}</textarea></div>`; break;
                    case 'button': specificProps = `<div><label>Button Text</label><input type="text" data-prop="text" value="${component.text || ''}"></div>`; break;
                    case 'checkbox': specificProps = `<div><label>Label</label><input type="text" data-prop="label" value="${component.label || ''}"></div><div><label class="flex items-center"><input type="checkbox" data-prop="checked" ${component.checked ? 'checked' : ''} class="mr-2 w-auto"> Is Checked</label></div>`; break;
                    case 'slider': specificProps = `<div class="grid grid-cols-3 gap-2"><div><label>Min</label><input type="number" data-prop="min" value="${component.min || 0}"></div><div><label>Max</label><input type="number" data-prop="max" value="${component.max || 100}"></div><div><label>Value</label><input type="number" data-prop="value" value="${component.value || 50}"></div></div>`; break;
                }
                const [tl, tr, br, bl] = parseBorderRadius(component.style.borderRadius);
                propertiesPanel.innerHTML = `
                    <details class="prop-group" open>
                        <summary>General</summary>
                        <div><label>Name (ID)</label><input type="text" data-prop="id" value="${component.id || ''}"></div>
                        ${specificProps}
                    </details>
                    <details class="prop-group" open>
                        <summary>Interaction</summary>
                        <div><label>Open Key (VK Code)</label><input type="text" data-interaction="openKey" value="${(component.interaction && component.interaction.openKey) || ''}" placeholder="e.g., 0x78"></div>
                        <div><label class="flex items-center"><input type="checkbox" data-interaction="useMasterKey" ${(component.interaction && component.interaction.useMasterKey) ? 'checked' : ''} class="mr-2 w-auto"> Use Master Key</label></div>
                    </details>
                    <details class="prop-group" open>
                        <summary>Layout</summary>
                        <div class="grid grid-cols-2 gap-2">
                            <div><label>X</label><input type="text" data-style="left" value="${component.style.left || ''}"></div>
                            <div><label>Y</label><input type="text" data-style="top" value="${component.style.top || ''}"></div>
                            <div><label>Width</label><input type="text" data-style="width" value="${component.style.width || ''}"></div>
                            <div><label>Height</label><input type="text" data-style="height" value="${component.style.height || ''}"></div>
                            <div><label>Z-Index</label><input type="number" data-style="zIndex" value="${component.style.zIndex || ''}"></div>
                            <div><label>Padding</label><input type="text" data-style="padding" value="${component.style.padding || ''}"></div>
                        </div>
                    </details>
                     <details class="prop-group" open>
                        <summary>Typography</summary>
                        <div class="grid grid-cols-2 gap-2">
                            <div><label>Color</label><input type="text" data-style="color" value="${component.style.color || ''}"></div>
                            <div><label>Font Size</label><input type="text" data-style="fontSize" value="${component.style.fontSize || ''}"></div>
                            <div><label>Font Family</label><input type="text" data-style="fontFamily" value="${component.style.fontFamily || ''}"></div>
                            <div><label>Font Weight</label><input type="text" data-style="fontWeight" value="${component.style.fontWeight || ''}"></div>
                            <div><label>Text Align</label><input type="text" data-style="textAlign" value="${component.style.textAlign || ''}"></div>
                            <div><label>Text Shadow</label><input type="text" data-style="textShadow" value="${component.style.textShadow || ''}"></div>
                        </div>
                    </details>
                    <details class="prop-group" open>
                        <summary>Appearance</summary>
                        <div><label>Background</label><textarea data-style="background">${component.style.background || ''}</textarea></div>
                        <div><label>Border</label><input type="text" data-style="border" value="${component.style.border || ''}"></div>
                        <label>Border Radius</label>
                        <div class="grid grid-cols-2 gap-2">
                            <div><input type="text" data-style-corner="tl" value="${tl}" placeholder="TL"></div>
                            <div><input type="text" data-style-corner="tr" value="${tr}" placeholder="TR"></div>
                            <div><input type="text" data-style-corner="br" value="${br}" placeholder="BR"></div>
                            <div><input type="text" data-style-corner="bl" value="${bl}" placeholder="BL"></div>
                        </div>
                        <div><label>Box Shadow</label><input type="text" data-style="boxShadow" value="${component.style.boxShadow || ''}"></div>
                        <div><label>Opacity</label><input type="text" data-style="opacity" value="${component.style.opacity || ''}"></div>
                        <div><label>Filter</label><input type="text" data-style="filter" value="${component.style.filter || ''}" placeholder="e.g., blur(5px) brightness(1.2)"></div>
                    </details>
                    <details class="prop-group" open>
                        <summary>Transform & Animation</summary>
                        <div><label>Transform</label><input type="text" data-style="transform" value="${component.style.transform || ''}" placeholder="e.g., rotate(45deg) scale(1.1)"></div>
                        <div><label>Transition</label><input type="text" data-style="transition" value="${component.style.transition || ''}" placeholder="e.g., all 0.3s ease"></div>
                        <div><label>Animation</label><input type="text" data-style="animation" value="${component.style.animation || ''}" placeholder="e.g., slide-in 1s ease-out"></div>
                    </details>
                    <details class="prop-group" open>
                        <summary>Keyframes</summary>
                        <div id="keyframes-container"></div>
                        <button id="add-keyframe-btn" class="mt-2 bg-blue-600 hover:bg-blue-700 text-white font-bold py-1 px-2 rounded text-xs">Add Keyframe Step</button>
                    </details>
                    <button id="delete-btn" class="mt-4 bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded w-full"><i class="fas fa-trash-alt mr-2"></i> Delete Element</button>
                `;
                
                document.getElementById('add-keyframe-btn').addEventListener('click', addKeyframe);
            }

            function addDragListeners(element, component) {
                 element.addEventListener('mousedown', e => {
                    if (e.target.closest('.resizer')) return;
                    e.stopPropagation();
                    selectComponent(component.id);
                    
                    const startMouseX = e.clientX;
                    const startMouseY = e.clientY;
                    const initialLeft = parseFloat(component.style.left || 0);
                    const initialTop = parseFloat(component.style.top || 0);
                    
                    const onMouseMove = moveEvent => {
                        moveEvent.preventDefault();
                        const dx = moveEvent.clientX - startMouseX;
                        const dy = moveEvent.clientY - startMouseY;
                        
                        element.style.transform = `translate(${dx}px, ${dy}px)`;
                        
                        const newLeft = initialLeft + dx;
                        const newTop = initialTop + dy;
                        const xInput = propertiesPanel.querySelector('[data-style="left"]');
                        const yInput = propertiesPanel.querySelector('[data-style="top"]');
                        if (xInput) xInput.value = `${newLeft}px`;
                        if (yInput) yInput.value = `${newTop}px`;
                    };

                    const onMouseUp = (moveEvent) => {
                        document.removeEventListener('mousemove', onMouseMove);
                        document.removeEventListener('mouseup', onMouseUp);
                        
                        const dx = moveEvent.clientX - startMouseX;
                        const dy = moveEvent.clientY - startMouseY;
                        component.style.left = `${initialLeft + dx}px`;
                        component.style.top = `${initialTop + dy}px`;
                        
                        element.style.transform = '';
                        renderAll(); 
                    };

                    document.addEventListener('mousemove', onMouseMove);
                    document.addEventListener('mouseup', onMouseUp);
                });
            }

            function addResizerListeners(resizer, element, component) {
                resizer.addEventListener('mousedown', e => {
                    e.stopPropagation();
                    const startMouseX = e.clientX, startMouseY = e.clientY;
                    const initialWidth = element.offsetWidth, initialHeight = element.offsetHeight;
                    const onMouseMove = moveEvent => {
                        component.style.width = `${initialWidth + (moveEvent.clientX - startMouseX)}px`;
                        component.style.height = `${initialHeight + (moveEvent.clientY - startMouseY)}px`;
                        element.style.width = component.style.width;
                        element.style.height = component.style.height;
                        const wInput = propertiesPanel.querySelector('[data-style="width"]');
                        const hInput = propertiesPanel.querySelector('[data-style="height"]');
                        if (wInput) wInput.value = component.style.width;
                        if (hInput) hInput.value = component.style.height;
                    };
                    const onMouseUp = () => {
                        document.removeEventListener('mousemove', onMouseMove);
                        document.removeEventListener('mouseup', onMouseUp);
                    };
                    document.addEventListener('mousemove', onMouseMove);
                    document.addEventListener('mouseup', onMouseUp);
                });
            }
            
            function addHierarchyDragListeners(element, component) {
                element.addEventListener('dragstart', e => { e.stopPropagation(); e.dataTransfer.setData('text/plain', component.id); e.dataTransfer.effectAllowed = 'move'; });
                element.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); element.style.backgroundColor = '#4b82f6'; });
                element.addEventListener('dragleave', e => { e.stopPropagation(); element.style.backgroundColor = ''; });
                element.addEventListener('drop', e => {
                    e.preventDefault(); e.stopPropagation();
                    element.style.backgroundColor = '';
                    const draggedId = e.dataTransfer.getData('text/plain');
                    if (draggedId === component.id) return;
                    const draggedComponent = findComponent(draggedId);
                    if (WIDGET_TYPES.includes(draggedComponent.type) && !['content', 'div', 'header', 'footer'].includes(component.type)) { alert('Widgets can only be placed inside a container like Content or Div.'); return; }
                    const oldParent = findParent(draggedId);
                    const sourceList = oldParent ? oldParent.children : components;
                    const index = sourceList.findIndex(c => c.id === draggedId);
                    if (index > -1) sourceList.splice(index, 1);
                    component.children.push(draggedComponent);
                    renderAll();
                });
            }

            toolbar.addEventListener('dragstart', e => e.dataTransfer.setData('text/plain', e.target.dataset.type));
            canvas.addEventListener('dragover', e => e.preventDefault());
            canvas.addEventListener('drop', e => {
                e.preventDefault();
                const typeOrId = e.dataTransfer.getData('text/plain');
                const targetWrapper = e.target.closest('.component-wrapper');
                const parentId = targetWrapper ? targetWrapper.dataset.id : null;
                const isNewComponent = [...toolbar.querySelectorAll('[draggable="true"]')].some(el => el.dataset.type === typeOrId);
                if (isNewComponent) { createComponent(typeOrId, parentId); }
            });
            
            propertiesPanel.addEventListener('change', e => {
                const component = findComponent(selectedComponentId);
                if (!component) return;
                
                const { prop, style, styleCorner, interaction } = e.target.dataset;
                let value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;

                if (prop) component[prop] = value;
                else if (style) {
                    if (style === 'backgroundImage' && value) value = `url('${value}')`;
                    component.style[style] = value;
                } else if (styleCorner) {
                    const [currentTl, currentTr, currentBr, currentBl] = parseBorderRadius(component.style.borderRadius);
                    let parts = [currentTl || '0px', currentTr || '0px', currentBr || '0px', currentBl || '0px'];
                    const cornerMap = { 'tl': 0, 'tr': 1, 'br': 2, 'bl': 3 };
                    parts[cornerMap[styleCorner]] = value;
                    component.style.borderRadius = parts.join(' ');
                } else if (interaction) {
                    if (!component.interaction) component.interaction = {};
                    component.interaction[interaction] = value;
                }
                
                renderAll();
            });
            
            elementJsEditor.addEventListener('input', e => { if(selectedComponentId) customJsMap[selectedComponentId] = e.target.value; });

            function deleteComponent(id, comps = components) { const index = comps.findIndex(c => c.id === id); if (index > -1) { comps.splice(index, 1); return true; } for (const comp of comps) { if (comp.children && deleteComponent(id, comp.children)) return true; } return false; }
            propertiesPanel.addEventListener('click', e => { if (e.target.id === 'delete-btn' && selectedComponentId) { deleteComponent(selectedComponentId); selectedComponentId = null; renderAll(); } });
            
            function showContextMenu(event, componentId) {
                contextMenu.style.display = 'block';
                contextMenu.style.left = `${event.clientX}px`; contextMenu.style.top = `${event.clientY}px`;
                contextMenu.innerHTML = `<div data-action="add" data-type="div"><i class="fas fa-square-full mr-2"></i> Add Div</div><div data-action="add" data-type="text"><i class="fas fa-font mr-2"></i> Add Text</div><hr class="my-1 border-gray-600"><div data-action="delete"><i class="fas fa-trash-alt mr-2"></i> Delete</div>`;
                contextMenu.dataset.targetId = componentId;
            }
            contextMenu.addEventListener('click', e => { const target = e.target.closest('div[data-action]'); if (!target) return; const { action, type } = target.dataset; const targetId = contextMenu.dataset.targetId; if (action === 'add') createComponent(type, targetId); else if (action === 'delete') { deleteComponent(targetId); if (selectedComponentId === targetId) selectedComponentId = null; renderAll(); } contextMenu.style.display = 'none'; });
            document.addEventListener('click', () => contextMenu.style.display = 'none');

            // --- Panel Resizing and Toggling Logic ---
            const layout = document.getElementById('main-layout');
            const panels = {
                elements: document.getElementById('elements-panel'),
                hierarchy: document.getElementById('hierarchy-panel-container'),
                properties: document.getElementById('properties-panel-container')
            };
            const resizers = {
                v1: document.getElementById('resizer-v1'),
                v2: document.getElementById('resizer-v2'),
                v3: document.getElementById('resizer-v3'),
                h1: document.getElementById('resizer-h1')
            };

            const panelSizes = {
                elements: '224px',
                hierarchy: '288px',
                properties: '384px'
            };

            function updateGridTemplate() {
                const cols = [
                    panels.elements.style.display === 'none' ? '0px' : panelSizes.elements,
                    panels.elements.style.display === 'none' ? '0px' : '5px',
                    panels.hierarchy.style.display === 'none' ? '0px' : panelSizes.hierarchy,
                    panels.hierarchy.style.display === 'none' ? '0px' : '5px',
                    '1fr',
                    panels.properties.style.display === 'none' ? '0px' : '5px',
                    panels.properties.style.display === 'none' ? '0px' : panelSizes.properties
                ];
                layout.style.gridTemplateColumns = cols.join(' ');
            }

            function initResizer(resizer, panelKey, colIndex) {
                resizer.addEventListener('mousedown', e => {
                    e.preventDefault();
                    const startX = e.clientX;
                    const initialWidth = parseFloat(panelSizes[panelKey]);

                    const onMouseMove = moveEvent => {
                        const dx = moveEvent.clientX - startX;
                        panelSizes[panelKey] = `${initialWidth + dx}px`;
                        updateGridTemplate();
                    };
                    const onMouseUp = () => {
                        document.removeEventListener('mousemove', onMouseMove);
                        document.removeEventListener('mouseup', onMouseUp);
                    };
                    document.addEventListener('mousemove', onMouseMove);
                    document.addEventListener('mouseup', onMouseUp);
                });
            }
            initResizer(resizers.v1, 'elements', 0);
            initResizer(resizers.v2, 'hierarchy', 2);
            
            resizers.v3.addEventListener('mousedown', e => {
                e.preventDefault();
                const startX = e.clientX;
                const initialWidth = parseFloat(panelSizes.properties);
                const onMouseMove = moveEvent => {
                    const dx = startX - moveEvent.clientX;
                    panelSizes.properties = `${initialWidth + dx}px`;
                    updateGridTemplate();
                };
                const onMouseUp = () => { document.removeEventListener('mousemove', onMouseMove); document.removeEventListener('mouseup', onMouseUp); };
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });
            
            resizers.h1.addEventListener('mousedown', e => {
                e.preventDefault();
                const canvasSection = document.getElementById('canvas-section');
                const startY = e.clientY;
                const initialHeight = document.getElementById('canvas-wrapper').offsetHeight;
                const onMouseMove = moveEvent => {
                    const dy = moveEvent.clientY - startY;
                    const newCanvasHeight = initialHeight + dy;
                    canvasSection.style.gridTemplateRows = `${newCanvasHeight}px 5px 1fr`;
                };
                const onMouseUp = () => { document.removeEventListener('mousemove', onMouseMove); document.removeEventListener('mouseup', onMouseUp); };
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });

            document.getElementById('toggle-elements').addEventListener('click', () => {
                panels.elements.style.display = panels.elements.style.display === 'none' ? 'flex' : 'none';
                resizers.v1.style.display = resizers.v1.style.display === 'none' ? 'block' : 'none';
                updateGridTemplate();
            });
            document.getElementById('toggle-hierarchy').addEventListener('click', () => {
                panels.hierarchy.style.display = panels.hierarchy.style.display === 'none' ? 'flex' : 'none';
                resizers.v2.style.display = resizers.v2.style.display === 'none' ? 'block' : 'none';
                updateGridTemplate();
            });
            document.getElementById('toggle-properties').addEventListener('click', () => {
                panels.properties.style.display = panels.properties.style.display === 'none' ? 'flex' : 'none';
                resizers.v3.style.display = resizers.v3.style.display === 'none' ? 'block' : 'none';
                updateGridTemplate();
            });


            importBtn.addEventListener('click', async () => {
                const result = await window.pywebview.api.import_html();
                if (result.status === 'success') {
                    const data = result.data;
                    components = data.components;
                    nextId = data.nextId;
                    globalCssEditor.value = data.globalCss || '';
                    customJsMap = {};
                    selectedComponentId = null;
                    renderAll();
                } else { alert(result.message); }
            });
            exportBtn.addEventListener('click', async () => { const result = await window.pywebview.api.export_html({ components, css: globalCssEditor.value, js: customJsMap }); alert(result.message); });
            saveLuaBtn.addEventListener('click', async () => { const result = await window.pywebview.api.save_lua({ components, css: globalCssEditor.value, js: customJsMap, globalSettings }); alert(result.message); });
            loadBtn.addEventListener('click', async () => { const result = await window.pywebview.api.load_project(); if (result.status === 'success') { const data = result.data; components = data.components; nextId = data.nextId; globalCssEditor.value = data.globalCss || ''; customJsMap = data.customJsMap || {}; selectedComponentId = null; renderAll(); } else { alert(result.message); } });
            
            // Keyframe Logic
            function addKeyframe() {
                const component = findComponent(selectedComponentId);
                if (!component) return;
                
                const step = prompt("Enter keyframe step (e.g., 0%, 50%, 100%, from, to):", "100%");
                if (!step) return;

                if (!component.keyframes) component.keyframes = {};
                component.keyframes[step] = { ...component.style };

                updateKeyframesUI();
                generateKeyframeCSS();
            }

            function updateKeyframesUI() {
                // ... UI update logic for keyframes panel ...
            }

            function generateKeyframeCSS() {
                const component = findComponent(selectedComponentId);
                if (!component || !component.keyframes || Object.keys(component.keyframes).length < 2) return;

                let animationName = component.style.animationName;
                if (!animationName) {
                    animationName = `anim-${component.id}`;
                    component.style.animationName = animationName;
                    if (!component.style.animationDuration) component.style.animationDuration = '2s';
                    if (!component.style.animationIterationCount) component.style.animationIterationCount = 'infinite';
                    updatePropertiesPanel();
                }

                let keyframeRule = `\\n@keyframes ${animationName} {\\n`;
                for (const step in component.keyframes) {
                    keyframeRule += `  ${step} {\\n`;
                    for (const prop in component.keyframes[step]) {
                        const cssProp = prop.replace(/([A-Z])/g, "-$1").toLowerCase();
                        keyframeRule += `    ${cssProp}: ${component.keyframes[step][prop]};\\n`;
                    }
                    keyframeRule += `  }\\n`;
                }
                keyframeRule += `}\\n`;
                
                // Remove old definition and add new one
                let css = globalCssEditor.value;
                const regex = new RegExp(`@keyframes ${animationName} \\{[\\s\\S]*?\\}`, 'g');
                css = css.replace(regex, '');
                globalCssEditor.value = css + keyframeRule;
            }

            document.getElementById('master-key').addEventListener('change', (e) => {
                globalSettings.masterKey = e.target.value;
            });

            renderAll();
        });
    </script>
</body>
</html>
"""

class Api:
    def __init__(self):
        self.window = None

    def export_html(self, payload):
        if not self.window: return {'status': 'error', 'message': 'Window not available'}
        try:
            file_path = self.window.create_file_dialog(webview.SAVE_DIALOG, file_types=('HTML File (*.html)',))
            if file_path:
                _, full_html = generate_html(payload['components'], payload['css'], payload['js'])
                with open(file_path[0], 'w', encoding='utf-8') as f: f.write(full_html)
                return {'status': 'success', 'message': f'Successfully exported to {file_path[0]}'}
            return {'status': 'info', 'message': 'Export cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def save_lua(self, payload):
        if not self.window: return {'status': 'error', 'message': 'Window not available'}
        try:
            file_path = self.window.create_file_dialog(webview.SAVE_DIALOG, file_types=('Lua Script (*.lua)',))
            if file_path:
                lua_code = generate_lua_script(payload)
                with open(file_path[0], 'w', encoding='utf-8') as f: f.write(lua_code)
                return {'status': 'success', 'message': f'Successfully saved to {file_path[0]}'}
            return {'status': 'info', 'message': 'Save cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def load_project(self):
        if not self.window: return {'status': 'error', 'message': 'Window not available'}
        try:
            file_path = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=('JSON Project (*.json)',))
            if file_path:
                with open(file_path[0], 'r', encoding='utf-8') as f: data = json.load(f)
                return {'status': 'success', 'data': data}
            return {'status': 'info', 'message': 'Load cancelled.'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
            
    def import_html(self):
        if not self.window: return {'status': 'error', 'message': 'Window not available'}
        try:
            file_path = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=('HTML Files (*.html;*.htm)',))
            if not file_path:
                return {'status': 'info', 'message': 'Import cancelled.'}
            
            actual_path = file_path[0] if isinstance(file_path, (list, tuple)) else file_path

            with open(actual_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            _next_id = 1
            def get_next_id():
                nonlocal _next_id
                val = _next_id
                _next_id += 1
                return val

            components = []
            body = soup.find('body')
            if body:
                for element in body.find_all(recursive=False):
                    parsed_el = parse_html_element(element, get_next_id)
                    if parsed_el:
                        components.append(parsed_el)
            
            head = soup.find('head')
            global_css = ""
            if head:
                for style_tag in head.find_all('style'):
                    global_css += style_tag.get_text(separator='\\n') + "\\n"

            return {'status': 'success', 'data': {'components': components, 'globalCss': global_css, 'nextId': _next_id}}
        except Exception as e:
            return {'status': 'error', 'message': f'Error parsing HTML: {str(e)}\\n{traceback.format_exc()}'}


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = s.getsockname()[1]
        
    flask_thread = threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port, debug=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    api = Api()
    window = webview.create_window('Visual Web Editor', f'http://127.0.0.1:{port}', js_api=api, width=1800, height=1000)
    api.window = window
    webview.start()
