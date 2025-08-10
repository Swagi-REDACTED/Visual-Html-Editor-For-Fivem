import re
import json
from bs4 import BeautifulSoup

def generate_html(project_data):
    """Generates a complete, runnable HTML file from the project structure."""
    components = project_data.get('components', [])
    global_css = project_data.get('globalCss', '')
    global_js = project_data.get('globalJs', '')
    element_css_map = project_data.get('elementCss', {})
    element_js_map = project_data.get('elementJs', {})

    def style_to_css(style_obj):
        """Converts a camelCase style object to a CSS string."""
        if not style_obj:
            return ""
        css_rules = []
        for key, value in style_obj.items():
            prop = re.sub(r'(?<!^)(?=[A-Z])', '-', key).lower()
            if value:
                css_rules.append(f"{prop}: {value};")
        return " ".join(css_rules)

    def build_elements_recursive(comps):
        """
        Recursively builds HTML elements from the component tree,
        correctly handling interspersed text nodes.
        """
        elements = []
        # Sort by zIndex for element nodes, text nodes have no z-index
        sorted_comps = sorted(comps, key=lambda c: int(c.get('style', {}).get('zIndex', 0)) if c.get('type') != 'textnode' else 0)
        
        for comp in sorted_comps:
            # ** FIX: Handle text nodes as plain text content **
            if comp.get('type') == 'textnode':
                elements.append(comp.get('text', ''))
                continue

            # Process normal element components
            inline_style = style_to_css(comp.get('style', {}))
            tag = comp.get('tag', 'div')
            
            children_html = build_elements_recursive(comp.get('children', []))
            
            attributes = f'id="{comp["id"]}" style="{inline_style}"'
            if comp.get('attributes'):
                for key, value in comp['attributes'].items():
                    if key.lower() not in ['style', 'id']:
                        attr_value = " ".join(value) if isinstance(value, list) else value
                        attributes += f' {key}="{attr_value}"'
            
            if tag in ['img', 'input', 'br', 'hr']: # Self-closing tags
                 elements.append(f'<{tag} {attributes}>')
            else:
                 # ** FIX: No longer adds a separate 'text_content' variable **
                 elements.append(f'<{tag} {attributes}>{children_html}</{tag}>')
        
        return "\n".join(elements)

    body_html = build_elements_recursive(components)
    
    element_specific_css = [
        f"#{comp_id} {{ {css_content} }}" for comp_id, css_content in element_css_map.items() if css_content
    ]
    full_css = f"{global_css}\n{'\n'.join(element_specific_css)}"

    element_scripts = [
        f"try{{ const el=document.getElementById('{comp_id}'); if(el){{ (function(el){{ {script} }})(el); }} }}catch(e){{console.error('Error in script for {comp_id}:',e)}}"
        for comp_id, script in element_js_map.items() if script
    ]
    full_script = f"{global_js}\ndocument.addEventListener('DOMContentLoaded',()=>{{{ ''.join(element_scripts) }}});"

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Exported Page</title>
    <style>
        body {{ margin: 0; padding: 0; font-family: sans-serif; }}
        {full_css}
    </style>
</head>
<body>
    {body_html}
    <script>
        {full_script}
    </script>
</body>
</html>"""
    return body_html, html_template

def generate_lua_script(project_data):
    """
    Generates a runnable Macho API Lua script from the project data.
    """
    _, full_html = generate_html(project_data)
    soup = BeautifulSoup(full_html, 'lxml')
    body_tag = soup.find('body')
    body_html_str = body_tag.decode_contents(formatter="html") if body_tag else ''
    style_tag = soup.find('style')
    css_str = style_tag.string if style_tag else ''
    script_tag = soup.find('script')
    js_str = script_tag.string if script_tag else ''

    def sanitize_for_lua_multiline(text_string):
        if not text_string:
            return ""
        return text_string.replace('[=[', '[==[').replace(']=]', ']==]')

    def component_to_lua_table(comp):
        lua_parts = []
        
        # ** FIX: Find the first text node child for the item's text **
        text = ""
        for child in comp.get('children', []):
            if child.get('type') == 'textnode':
                text = child.get('text', '').strip()
                break
        
        # ** FIX: Check for non-textnode children to determine if it's a submenu **
        has_element_children = any(c.get('type') != 'textnode' for c in comp.get('children', []))

        lua_type = "action"
        if 'checkbox' in comp.get('attributes', {}).get('class', []):
            lua_type = "checkbox"
        if 'slider' in comp.get('attributes', {}).get('class', []):
            lua_type = "slidercb" if lua_type == "checkbox" else "slider"
        if has_element_children:
            lua_type = "submenu"

        lua_parts.append(f"text = \"{text}\"")
        lua_parts.append(f"type = \"{lua_type}\"")
        
        if lua_type == "submenu":
            lua_parts.append(f"target = \"{comp['id']}\"")
        
        if lua_type != "action" and lua_type != "submenu":
            lua_parts.append(f"state = Functions.{comp['id'].replace('-', '_')}_state")
            lua_parts.append(f"action = function(s, v) Functions.{comp['id'].replace('-', '_')}_state, Functions.{comp['id'].replace('-', '_')}_value = s, v end")
        
        if lua_type.startswith("slider"):
            lua_parts.append(f"value = Functions.{comp['id'].replace('-', '_')}_value")
            lua_parts.append(f"min = {comp.get('attributes', {}).get('data-min', 0)}")
            lua_parts.append(f"max = {comp.get('attributes', {}).get('data-max', 100)}")
            lua_parts.append(f"step = {comp.get('attributes', {}).get('data-step', 1)}")

        return f"{{ {', '.join(lua_parts)} }}"

    lua_menu_structure = ["menuStructure = {"]
    
    def build_menu_recursive(comps, parent_id="main"):
        lua_menu_structure.append(f"    {parent_id} = {{")
        lua_menu_structure.append(f"        title = \"{parent_id.replace('_', ' ').title()}\",")
        lua_menu_structure.append(f"        items = {{")
        
        child_submenus = []
        for comp in comps:
            # Only process actual elements, not text nodes, as menu items
            if comp.get('type') != 'textnode':
                lua_menu_structure.append(f"            {component_to_lua_table(comp)},")
                if any(c.get('type') != 'textnode' for c in comp.get('children', [])):
                    child_submenus.append(comp)

        lua_menu_structure.append("            { text = \"Back\", type = \"back\" },")
        lua_menu_structure.append("        }")
        lua_menu_structure.append("    },")

        for sub in child_submenus:
            build_menu_recursive(sub['children'], sub['id'])

    build_menu_recursive(project_data.get('components', []))
    lua_menu_structure.append("}")

    functions_table = ["local Functions = {"]
    def find_all_components(comps):
        all_comps = []
        for comp in comps:
            if comp.get('type') != 'textnode':
                all_comps.append(comp)
                all_comps.extend(find_all_components(comp.get('children', [])))
        return all_comps

    for comp in find_all_components(project_data.get('components', [])):
        comp_id_lua = comp['id'].replace('-', '_')
        functions_table.append(f"    {comp_id_lua}_state = false,")
        functions_table.append(f"    {comp_id_lua}_value = 0,")
    functions_table.append("}")

    lua_script = f"""-- Generated by Visual Web Editor
-- Macho API Ready Lua Structure

-- #region State Management
{'\n'.join(functions_table)}
-- #endregion

-- #region Menu Structure
{'\n'.join(lua_menu_structure)}
-- #endregion

Citizen.CreateThread(function()
    local htmlPayload = [=[
        <!DOCTYPE html>
        <html>
        <head>
            <style>{sanitize_for_lua_multiline(css_str)}</style>
        </head>
        <body>{sanitize_for_lua_multiline(body_html_str)}</body>
        </html>
    ]=]
    
    local jsPayload = [=[{sanitize_for_lua_multiline(js_str)}]=]

    MachoInjectPayload(htmlPayload, jsPayload)
end)

-- Placeholder for key handlers and other logic
MachoOnKeyUp(function(key)
    -- Your key handling logic here
end)

print("Macho DUI script with structured menu loaded successfully.")
"""
    return lua_script
