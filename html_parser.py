import os
import re
import base64
from bs4 import BeautifulSoup, NavigableString
import cssutils
import logging

# Configure cssutils to be less verbose with expected parsing errors
cssutils.log.setLevel(logging.CRITICAL)

def _camel_case(s):
    """Converts a kebab-case string to camelCase."""
    parts = s.split('-')
    return parts[0] + ''.join(x.capitalize() for x in parts[1:])

def _get_specificity(selector_text):
    """
    Calculates the specificity of a CSS selector based on the W3C spec.
    Returns a tuple (a, b, c) for IDs, classes/attributes, and elements.
    """
    spec = [0, 0, 0]
    # Strip pseudo-classes and pseudo-elements for matching, but account for some structural ones in specificity
    selector = re.sub(r'::?[\w-]+(\(.*\))?', '', selector_text)
    
    # a: Count IDs
    spec[0] = len(re.findall(r'#[\w-]+', selector))
    
    # b: Count classes, attributes, and some pseudo-classes
    spec[1] = len(re.findall(r'\.[\w-]+', selector)) + \
              len(re.findall(r'\[.*?\]', selector)) + \
              len(re.findall(r':(not|where|is|has|hover|focus|active|checked|disabled|enabled|target|root|empty|first-child|last-child|nth-child)\b', selector_text))
              
    # c: Count elements and pseudo-elements
    spec[2] = len(re.findall(r'(?<![\.#\[:])\b[\w-]+', selector)) + \
              len(re.findall(r'::(before|after|first-line|first-letter|selection|marker|placeholder)', selector_text))
              
    return tuple(spec)

def _element_matches_selector(element, selector_part):
    """Checks if a single element matches a part of a selector (e.g., 'div.item#main')."""
    if not hasattr(element, 'name'):
        return False
    
    # Strip pseudo-classes and pseudo-elements for matching purposes
    selector_part_clean = re.sub(r'::?[\w-]+(\(.*\))?', '', selector_part)

    # Match tag name (e.g., 'div')
    tag_match = re.match(r'^[\w-]+', selector_part_clean)
    if tag_match and element.name != tag_match.group(0):
        return False

    # Match ID (e.g., '#main')
    id_match = re.search(r'#([\w-]+)', selector_part_clean)
    if id_match and element.get('id') != id_match.group(1):
        return False

    # Match classes (e.g., '.item', '.active')
    class_matches = re.findall(r'\.([\w-]+)', selector_part_clean)
    if class_matches and not all(c in element.get('class', []) for c in class_matches):
        return False
        
    # Match attributes (e.g., '[type="checkbox"]')
    attr_matches = re.findall(r'\[([\w-]+)(?:([*^$|~]?=)["\']?(.*?)["\']?)?\]', selector_part_clean)
    for attr_name, operator, attr_value in attr_matches:
        el_attr_val = element.get(attr_name)
        if el_attr_val is None: return False
        if operator:
            if operator == '=' and el_attr_val != attr_value: return False
            if operator == '~=' and attr_value not in el_attr_val.split(): return False
            if operator == '|=' and not (el_attr_val == attr_value or el_attr_val.startswith(attr_value + '-')): return False
            if operator == '^=' and not el_attr_val.startswith(attr_value): return False
            if operator == '$=' and not el_attr_val.endswith(attr_value): return False
            if operator == '*=' and attr_value not in el_attr_val: return False
    
    return True

def _matches_selector(element, selector_text):
    """
    More robust check if a BeautifulSoup element matches a given CSS selector.
    Handles descendant selectors correctly by ensuring the final part of the
    selector matches the element itself.
    """
    # Handle comma-separated selectors
    selectors = [s.strip() for s in selector_text.split(',')]
    for selector in selectors:
        parts = selector.split()
        
        # The last part of the selector (the target) must match the element itself.
        if not _element_matches_selector(element, parts[-1]):
            continue

        # If there are more parts (ancestors), they must match the parents in order.
        if len(parts) > 1:
            current_element = element.find_parent()
            is_match = True
            for part in reversed(parts[:-1]):
                found_ancestor_match = False
                temp_element = current_element
                while temp_element:
                    if _element_matches_selector(temp_element, part):
                        found_ancestor_match = True
                        current_element = temp_element.find_parent()
                        break
                    temp_element = temp_element.find_parent()
                
                if not found_ancestor_match:
                    is_match = False
                    break
            
            if is_match:
                return True
        else:
            return True # Only one part in the selector, and it matched.
            
    return False


def _compute_styles(element, stylesheet):
    """
    Computes the final styles for an element by applying all matching CSS rules
    from a stylesheet, respecting specificity.
    """
    computed_style = {}
    matching_rules = []

    if not hasattr(element, 'name'):
        return {}

    for rule in stylesheet:
        if rule.type == cssutils.css.CSSRule.STYLE_RULE:
            for selector in rule.selectorList:
                if _matches_selector(element, selector.selectorText):
                    specificity = _get_specificity(selector.selectorText)
                    matching_rules.append((specificity, rule.style))

    matching_rules.sort(key=lambda x: x[0])

    for _, style in matching_rules:
        for prop in style:
            computed_style[_camel_case(prop.name)] = prop.value
            
    return computed_style

def _determine_type(element):
    """Determines the component type based on tag."""
    tag = element.name
    if tag in ['header', 'footer', 'main', 'button', 'svg', 'img', 'p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'style', 'g', 'path', 'line', 'circle', 'rect', 'filter', 'fegaussianblur', 'fecolormatrix', 'feblend']:
        return tag
    if tag == 'input':
        return element.get('type', 'text')
    return 'div'

def _parse_html_element(element, next_id_func, stylesheet, base_path):
    """
    Recursively parses a BeautifulSoup element into the application's
    JSON component structure.
    """
    if not hasattr(element, 'name') or not element.name:
        return None

    comp_type = _determine_type(element)
    comp_id = element.get('id') or f"{comp_type}-{next_id_func()}"

    computed_styles = _compute_styles(element, stylesheet)

    inline_style_str = element.get('style', '')
    if inline_style_str:
        try:
            inline_parser = cssutils.parseStyle(inline_style_str)
            for prop in inline_parser:
                computed_styles[_camel_case(prop.name)] = prop.value
        except Exception:
            pass

    if comp_type == 'img':
        src = element.get('src')
        if src and not src.startswith(('http', 'data:')):
            try:
                with open(os.path.join(base_path, src), "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                    element['src'] = f"data:image/png;base64,{encoded_string}"
            except Exception as e:
                print(f"Warning: Image not found: {os.path.join(base_path, src)} - {e}")
    
    bg_image = computed_styles.get('backgroundImage', '')
    if 'url(' in bg_image:
        url_match = re.search(r'url\((.*?)\)', bg_image)
        if url_match:
            url = url_match.group(1).strip('\'"')
            if url and not url.startswith(('http', 'data:')):
                try:
                    with open(os.path.join(base_path, url), "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                        computed_styles['backgroundImage'] = f"url('data:image/png;base64,{encoded_string}')"
                except Exception as e:
                     print(f"Warning: Background image not found: {os.path.join(base_path, url)} - {e}")

    component = {
        'id': comp_id,
        'type': comp_type,
        'tag': element.name,
        'name': comp_id,
        'children': [],
        'style': computed_styles,
        'text': '',
        'attributes': {k: v for k, v in element.attrs.items() if k.lower() not in ['id', 'style']},
        'attachments': []
    }

    direct_text = []
    for content in element.contents:
        if isinstance(content, NavigableString) and content.strip():
            direct_text.append(content.strip())
        elif hasattr(content, 'name') and content.name:
            child_comp = _parse_html_element(content, next_id_func, stylesheet, base_path)
            if child_comp:
                component['children'].append(child_comp)
    
    if direct_text:
        component['text'] = ' '.join(direct_text)

    return component

def parse_html_to_project(html_content, base_path):
    """
    Main parsing function. Correctly handles complex HTML by using a robust parser
    and improved style computation.
    """
    soup = BeautifulSoup(html_content, 'lxml')
    
    full_css_text = ""
    head = soup.find('head')
    if head:
        for link_tag in head.find_all('link', rel='stylesheet'):
            href = link_tag.get('href')
            if href and not href.startswith('http'):
                try:
                    with open(os.path.join(base_path, href), 'r', encoding='utf-8') as f:
                        full_css_text += f.read() + "\n"
                except FileNotFoundError:
                    print(f"Warning: CSS file not found at {os.path.join(base_path, href)}")
        
        for style_tag in head.find_all('style'):
            full_css_text += style_tag.string or ''
            
    stylesheet = cssutils.parseString(full_css_text, validate=False)

    global_js = ""
    for script_tag in soup.find_all('script'):
        src = script_tag.get('src')
        if src and not src.startswith('http'):
             try:
                with open(os.path.join(base_path, src), 'r', encoding='utf-8') as f:
                    global_js += f.read() + "\n"
             except FileNotFoundError:
                print(f"Warning: JS file not found at {os.path.join(base_path, src)}")
        elif script_tag.string:
            global_js += script_tag.string + "\n"
        script_tag.decompose()

    _next_id_counter = 1
    def get_next_id():
        nonlocal _next_id_counter
        val = _next_id_counter
        _next_id_counter += 1
        return val

    components = []
    body = soup.find('body')
    if body:
        # ** FIX: Parse the body tag itself as the root component **
        # This preserves all styles and attributes applied to the body,
        # which is crucial for overall layout.
        body_comp = _parse_html_element(body, get_next_id, stylesheet, base_path)
        if body_comp:
            components = [body_comp]

    return {
        'components': components,
        'globalCss': full_css_text,
        'globalJs': global_js,
        'elementCss': {},
        'elementJs': {},
        'nextId': _next_id_counter
    }
