document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Element References ---
    const canvas = document.getElementById('canvas');
    const toolbar = document.getElementById('toolbar');
    const hierarchyPanel = document.getElementById('hierarchy-panel');
    const propertiesPanel = document.getElementById('properties-panel');
    const contextMenu = document.getElementById('context-menu');
    const mainLayout = document.getElementById('main-layout');

    // Editors
    const globalCssEditor = document.getElementById('global-css');
    const globalJsEditor = document.getElementById('global-js');
    const elementCssEditor = document.getElementById('element-css');
    const elementJsEditor = document.getElementById('element-js');

    // Buttons
    const importBtn = document.getElementById('import-btn');
    const saveLuaBtn = document.getElementById('save-lua-btn');
    const loadBtn = document.getElementById('load-btn');
    const exportBtn = document.getElementById('export-btn');
    const saveProjectBtn = document.getElementById('save-project-btn');
    const toggleElementsBtn = document.getElementById('toggle-elements');
    const toggleHierarchyBtn = document.getElementById('toggle-hierarchy');
    const togglePropertiesBtn = document.getElementById('toggle-properties');

    // --- Application State ---
    let project = {
        components: [],
        globalCss: '',
        globalJs: '',
        elementCss: {},
        elementJs: {},
        globalSettings: { masterKey: '' },
        nextId: 1
    };
    let selectedComponentId = null;
    let contextMenuTargetId = null;
    let dragData = {}; // For more robust drag-and-drop

    // --- Core Functions ---

    function findComponent(id, comps = project.components) {
        for (const comp of comps) {
            if (comp.id === id) return comp;
            if (comp.children) {
                const found = findComponent(id, comp.children);
                if (found) return found;
            }
        }
        return null;
    }

    function findParent(childId, comps = project.components, parent = null) {
        for (const comp of comps) {
            if (comp.id === childId) return parent;
            if (comp.children) {
                const found = findParent(childId, comp.children, comp);
                if (found) return found;
            }
        }
        return null;
    }

    function getNewId() {
        const id = `element-${project.nextId++}`;
        return id;
    }

    function createComponent(type, parentId = null) {
        const id = getNewId();
        const parent = parentId ? findComponent(parentId) : null;
        const isFlexChild = parent?.style?.display === 'flex';

        let newComp = {
            id,
            type,
            tag: type,
            name: `${type}-${id.split('-')[1]}`,
            children: [],
            style: {
                position: isFlexChild ? 'relative' : 'absolute',
                width: isFlexChild ? 'auto' : '200px',
                height: isFlexChild ? '100px' : '100px',
                backgroundColor: '#555',
                border: '1px solid #888',
                borderRadius: '5px',
                padding: '10px',
                margin: isFlexChild ? '5px' : '0',
                zIndex: parent ? (parent.children?.length || 0) + 1 : project.components.length + 1,
                left: isFlexChild ? 'auto' : '20px',
                top: isFlexChild ? 'auto' : '20px',
            },
            text: '',
            attributes: {},
            interaction: {},
            attachments: []
        };

        switch (type) {
            case 'text':
                newComp.tag = 'p';
                newComp.text = 'Editable Text';
                newComp.style = { ...newComp.style, height: 'auto', backgroundColor: 'transparent', border: 'none', color: '#ffffff' };
                break;
            case 'button':
                newComp.tag = 'button';
                newComp.text = 'Button';
                newComp.style = { ...newComp.style, width: '120px', height: '40px', textAlign: 'center', cursor: 'pointer', display: 'grid', placeItems: 'center' };
                project.elementJs[id] = `el.addEventListener('click', () => {\n    el.classList.toggle('toggled');\n    console.log(\`\${el.id} clicked\`);\n});`;
                break;
            case 'img':
                newComp.tag = 'img';
                newComp.style = {...newComp.style, width: '100px', height: '100px', objectFit: 'cover', backgroundColor: 'transparent', border: 'none'};
                newComp.attributes.src = 'https://placehold.co/100x100/2a2d32/f0f0f0?text=Image';
                break;
            case 'header':
                newComp.tag = 'header';
                newComp.style = { ...newComp.style, height: '150px', width: '100%', left: '0px', top: '0px', borderRadius: '0px' };
                break;
            case 'div':
                newComp.style.display = 'flex'; // Default new divs to flex
                newComp.style.flexDirection = 'row';
                break;
            case 'svg':
                newComp.tag = 'svg';
                newComp.attributes = { viewBox: '0 0 24 24', fill: 'currentColor' };
                newComp.style = { ...newComp.style, width: '24px', height: '24px', backgroundColor: 'transparent', border: 'none' };
                newComp.children = [{
                    id: getNewId(), type: 'path', tag: 'path', name: 'path-1', children: [], style: {}, text: '',
                    attributes: { d: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z' }
                }];
                break;
        }

        if (parent) {
            parent.children.push(newComp);
        } else {
            project.components.push(newComp);
        }
        renderAll();
        selectComponent(id);
    }
    
    function deleteComponent(id) {
        const parent = findParent(id);
        const sourceList = parent ? parent.children : project.components;
        const index = sourceList.findIndex(c => c.id === id);
        if (index > -1) {
            sourceList.splice(index, 1);
            delete project.elementCss[id];
            delete project.elementJs[id];
            return true;
        }
        return false;
    }

    // --- Rendering Functions ---

    function renderAll() {
        canvas.innerHTML = '';
        hierarchyPanel.innerHTML = '';
        
        const hierarchyRoot = document.createElement('ul');
        project.components.forEach(comp => {
            const wrapper = renderComponentOnCanvas(comp);
            if (wrapper) canvas.appendChild(wrapper);
            hierarchyRoot.appendChild(renderComponentInHierarchy(comp));
        });
        hierarchyPanel.appendChild(hierarchyRoot);
        
        updatePropertiesPanel();
    }

    function renderComponentOnCanvas(component) {
        const wrapper = document.createElement(component.tag || 'div');
        wrapper.className = 'component-wrapper';
        wrapper.id = component.id;
        wrapper.dataset.id = component.id;
        wrapper.dataset.name = component.name;

        if (selectedComponentId === component.id) wrapper.classList.add('selected');
        
        Object.keys(component.style).forEach(key => { wrapper.style[key] = component.style[key]; });

        if (component.attributes) {
            Object.keys(component.attributes).forEach(key => {
                if (key === 'class' && Array.isArray(component.attributes[key])) {
                    wrapper.classList.add(...component.attributes[key]);
                } else {
                    wrapper.setAttribute(key, component.attributes[key]);
                }
            });
        }
        
        if (component.text) {
            wrapper.appendChild(document.createTextNode(component.text));
        }

        // Add layout-specific classes for drag-and-drop handling
        if (component.style.display === 'flex') {
            wrapper.classList.add('flex-layout-container');
        }
        const parent = findParent(component.id);
        if (parent && parent.style.display === 'flex') {
            wrapper.classList.add('flex-layout-item');
        }
       
        if (component.children && component.children.length > 0) {
            component.children.forEach(child => {
                const childEl = renderComponentOnCanvas(child);
                if (childEl) wrapper.appendChild(childEl);
            });
        }

        addInteractionListeners(wrapper, component);
        if (selectedComponentId === component.id) {
            const resizer = document.createElement('div');
            resizer.className = 'resizer br';
            wrapper.appendChild(resizer);
            addResizerListeners(resizer, wrapper, component);
        }
        return wrapper;
    }

    function renderComponentInHierarchy(component) {
        const li = document.createElement('li');
        li.className = `component-item ${component.type}`;
        if (selectedComponentId === component.id) li.classList.add('selected');
        li.dataset.id = component.id;
        li.draggable = true;
        
        const ICONS = { header: 'fa-window-maximize', content: 'fa-align-justify', footer: 'fa-shoe-prints', div: 'fa-square-full', text: 'fa-font', button: 'fa-mouse-pointer', img: 'fa-image', svg: 'fa-vector-square', checkbox: 'fa-check-square', slider: 'fa-sliders-h' };
        li.innerHTML = `<i class="fas ${ICONS[component.type] || 'fa-question-circle'} mr-2 w-4"></i><span>${component.name}</span>`;
        
        li.addEventListener('click', e => { e.stopPropagation(); selectComponent(component.id); });
        li.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); showContextMenu(e, component.id); });
        addHierarchyDragListeners(li);

        if (component.children && component.children.length > 0) {
            const childrenUl = document.createElement('ul');
            childrenUl.className = 'hierarchy-children';
            component.children.forEach(child => childrenUl.appendChild(renderComponentInHierarchy(child)));
            li.appendChild(childrenUl);
        }
        return li;
    }
    
    function updatePropertiesPanel() {
        const component = findComponent(selectedComponentId);
        if (!component) {
            propertiesPanel.innerHTML = '<p class="text-gray-400">Select an element to edit.</p>';
            return;
        }

        const parent = findParent(selectedComponentId);
        const isFlexChild = parent?.style.display === 'flex';
        
        const createProp = (label, prop, value, type = 'text') => `<div><label>${label}</label><input type="${type}" data-prop="${prop}" value="${value || ''}"></div>`;
        const createStyle = (label, style, value, type = 'text') => `<div><label>${label}</label><input type="${type}" data-style="${style}" value="${value || ''}"></div>`;
        const createSelect = (label, style, value, options) => `<div><label>${label}</label><select data-style="${style}">${options.map(o => `<option value="${o}" ${value === o ? 'selected' : ''}>${o}</option>`).join('')}</select></div>`;

        const generalProps = `
            ${createProp('Name', 'name', component.name)}
            <div><label>ID</label><input type="text" value="${component.id}" readonly class="bg-gray-700 cursor-not-allowed"></div>
            <div><label>Text Content</label><textarea data-prop="text">${component.text || ''}</textarea></div>
        `;

        let layoutProps = `
            <details class="prop-group" open><summary>Position & Size</summary><div class="p-2 space-y-2">
            ${createSelect('Position', 'position', component.style.position, ['absolute', 'relative', 'static', 'fixed', 'sticky'])}
            <div class="prop-grid">
                ${createStyle('Left', 'left', component.style.left)}
                ${createStyle('Top', 'top', component.style.top)}
                ${createStyle('Right', 'right', component.style.right)}
                ${createStyle('Bottom', 'bottom', component.style.bottom)}
                ${createStyle('Width', 'width', component.style.width)}
                ${createStyle('Height', 'height', component.style.height)}
                ${createStyle('Min W', 'minWidth', component.style.minWidth)}
                ${createStyle('Min H', 'minHeight', component.style.minHeight)}
                ${createStyle('Max W', 'maxWidth', component.style.maxWidth)}
                ${createStyle('Max H', 'maxHeight', component.style.maxHeight)}
            </div>
            </div></details>
        `;

        let flexContainerProps = '';
        if (component.style.display === 'flex') {
            flexContainerProps = `
                <details class="prop-group" open><summary>Flex Container</summary><div class="p-2 space-y-2">
                <div class="prop-grid">
                    ${createSelect('Direction', 'flexDirection', component.style.flexDirection, ['row', 'column', 'row-reverse', 'column-reverse'])}
                    ${createSelect('Wrap', 'flexWrap', component.style.flexWrap, ['nowrap', 'wrap', 'wrap-reverse'])}
                    ${createSelect('Justify Content', 'justifyContent', component.style.justifyContent, ['flex-start', 'center', 'flex-end', 'space-between', 'space-around', 'space-evenly'])}
                    ${createSelect('Align Items', 'alignItems', component.style.alignItems, ['flex-start', 'center', 'flex-end', 'stretch', 'baseline'])}
                    ${createSelect('Align Content', 'alignContent', component.style.alignContent, ['flex-start', 'center', 'flex-end', 'space-between', 'space-around', 'stretch'])}
                    ${createStyle('Gap', 'gap', component.style.gap)}
                </div>
                </div></details>
            `;
        }
        
        let flexItemProps = '';
        if (isFlexChild) {
            flexItemProps = `
                <details class="prop-group" open><summary>Flex Item</summary><div class="p-2 space-y-2">
                <div class="prop-grid">
                    ${createStyle('Flex Grow', 'flexGrow', component.style.flexGrow, 'number')}
                    ${createStyle('Flex Shrink', 'flexShrink', component.style.flexShrink, 'number')}
                    ${createStyle('Flex Basis', 'flexBasis', component.style.flexBasis)}
                    ${createStyle('Order', 'order', component.style.order, 'number')}
                    ${createSelect('Align Self', 'alignSelf', component.style.alignSelf, ['auto', 'flex-start', 'center', 'flex-end', 'stretch', 'baseline'])}
                </div>
                </div></details>
            `;
        }

        const appearanceProps = `
            <details class="prop-group"><summary>Appearance</summary><div class="p-2 space-y-2">
                ${createSelect('Display', 'display', component.style.display, ['block', 'inline-block', 'flex', 'grid', 'inline', 'none'])}
                ${createStyle('Background', 'background', component.style.background)}
                ${createStyle('Color', 'color', component.style.color, 'color')}
                ${createStyle('Border', 'border', component.style.border)}
                ${createStyle('Border Radius', 'borderRadius', component.style.borderRadius)}
                ${createStyle('Box Shadow', 'boxShadow', component.style.boxShadow)}
                ${createStyle('Opacity', 'opacity', component.style.opacity, 'number')}
                ${createStyle('Z-Index', 'zIndex', component.style.zIndex, 'number')}
                ${createSelect('Overflow', 'overflow', component.style.overflow, ['visible', 'hidden', 'scroll', 'auto'])}
            </div></details>
        `;
        
        const spacingProps = `
            <details class="prop-group"><summary>Spacing</summary><div class="p-2 space-y-2">
            <div class="prop-grid">
                ${createStyle('Margin', 'margin', component.style.margin)}
                ${createStyle('Padding', 'padding', component.style.padding)}
            </div>
            </div></details>
        `;

        propertiesPanel.innerHTML = `
            <details class="prop-group" open><summary>General</summary><div class="p-2 space-y-2">${generalProps}</div></details>
            ${layoutProps}
            ${flexContainerProps}
            ${flexItemProps}
            ${appearanceProps}
            ${spacingProps}
            <button id="delete-btn" class="mt-4 bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded w-full">Delete</button>
        `;
    }

    // --- Event Handlers & Listeners ---

    function selectComponent(id) {
        if (selectedComponentId === id) return;
        
        selectedComponentId = id;

        if (id) {
            elementCssEditor.value = project.elementCss[id] || '';
            elementJsEditor.value = project.elementJs[id] || '';
        } else {
            elementCssEditor.value = '';
            elementJsEditor.value = '';
        }
        
        renderAll();
    }

    function addInteractionListeners(element, component) {
        const isFlexItem = element.classList.contains('flex-layout-item');
        element.draggable = isFlexItem; // Only flex items are draggable for reordering

        // Mousedown for selecting and absolute dragging
        element.addEventListener('mousedown', e => {
            if (e.target.closest('.resizer')) return;
            e.stopPropagation();
            selectComponent(component.id);
            
            // Allow dragging only if the element is absolutely positioned
            if (component.style.position !== 'absolute') return;

            const startMouseX = e.clientX, startMouseY = e.clientY;
            const initialLeft = parseFloat(component.style.left || 0), initialTop = parseFloat(component.style.top || 0);
            
            const onMouseMove = moveEvent => {
                const dx = moveEvent.clientX - startMouseX, dy = moveEvent.clientY - startMouseY;
                component.style.left = `${initialLeft + dx}px`;
                component.style.top = `${initialTop + dy}px`;
                element.style.left = component.style.left;
                element.style.top = component.style.top;
            };
            
            const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                updatePropertiesPanel();
            };
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });

        // --- Flexbox Drag-and-Drop Logic ---
        element.addEventListener('dragstart', e => {
            if (!isFlexItem) { e.preventDefault(); return; }
            e.stopPropagation();
            dragData.sourceId = component.id;
            e.dataTransfer.setData('text/plain', component.id);
            e.dataTransfer.effectAllowed = 'move';
            setTimeout(() => e.target.style.opacity = '0.5', 0);
        });

        element.addEventListener('dragend', e => {
            if (!isFlexItem) return;
            e.stopPropagation();
            e.target.style.opacity = '1';
            dragData = {};
            document.querySelectorAll('.drag-placeholder').forEach(p => p.remove());
        });

        element.addEventListener('dragover', e => {
            if (!dragData.sourceId) return;

            const targetContainer = e.target.closest('.flex-layout-container');
            if (!targetContainer) return;
            
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = 'move';

            const placeholder = getPlaceholder();
            const targetItem = e.target.closest('.flex-layout-item');
            
            if (targetItem && targetItem.id !== dragData.sourceId) {
                const rect = targetItem.getBoundingClientRect();
                const parentComp = findComponent(targetContainer.dataset.id);
                const isColumn = parentComp.style.flexDirection?.includes('column');
                const isAfter = isColumn ? (e.clientY > rect.top + rect.height / 2) : (e.clientX > rect.left + rect.width / 2);
                targetContainer.insertBefore(placeholder, isAfter ? targetItem.nextSibling : targetItem);
            } else if (!targetItem) {
                targetContainer.appendChild(placeholder);
            }
        });

        element.addEventListener('drop', e => {
            if (!dragData.sourceId) return;
            e.preventDefault();
            e.stopPropagation();
            
            const placeholder = document.querySelector('.drag-placeholder');
            if (!placeholder || !placeholder.parentNode) return;

            const oldParent = findParent(dragData.sourceId);
            const newParent = findComponent(placeholder.parentNode.dataset.id);
            if (!oldParent || !newParent) return;

            const sourceIndex = oldParent.children.findIndex(c => c.id === dragData.sourceId);
            const [draggedComp] = oldParent.children.splice(sourceIndex, 1);
            
            const placeholderIndex = Array.from(placeholder.parentNode.children).indexOf(placeholder);
            newParent.children.splice(placeholderIndex, 0, draggedComp);

            renderAll();
        });
    }

    function getPlaceholder() {
        let placeholder = document.querySelector('.drag-placeholder');
        if (!placeholder) {
            placeholder = document.createElement('div');
            placeholder.className = 'drag-placeholder';
            const draggedEl = document.getElementById(dragData.sourceId);
            if (draggedEl) {
                placeholder.style.width = draggedEl.offsetWidth + 'px';
                placeholder.style.height = draggedEl.offsetHeight + 'px';
            }
        }
        return placeholder;
    }

    function addResizerListeners(resizer, element, component) {
        resizer.addEventListener('mousedown', e => {
            e.preventDefault();
            e.stopPropagation();
            const startMouseX = e.clientX, startMouseY = e.clientY;
            const initialWidth = element.offsetWidth, initialHeight = element.offsetHeight;
            
            const onMouseMove = moveEvent => {
                component.style.width = `${initialWidth + (moveEvent.clientX - startMouseX)}px`;
                component.style.height = `${initialHeight + (moveEvent.clientY - startMouseY)}px`;
                element.style.width = component.style.width;
                element.style.height = component.style.height;
            };
            
            const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                updatePropertiesPanel();
            };
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }

    function addHierarchyDragListeners(element) {
        element.addEventListener('dragstart', e => {
            e.stopPropagation();
            e.dataTransfer.setData('text/plain', element.dataset.id);
            e.dataTransfer.effectAllowed = 'move';
        });

        element.addEventListener('dragover', e => {
            e.preventDefault();
            e.stopPropagation();
            element.style.backgroundColor = '#4b82f6';
        });

        element.addEventListener('dragleave', e => {
            e.stopPropagation();
            element.style.backgroundColor = '';
        });

        element.addEventListener('drop', e => {
            e.preventDefault();
            e.stopPropagation();
            element.style.backgroundColor = '';
            
            const draggedId = e.dataTransfer.getData('text/plain');
            const targetId = element.dataset.id;
            if (draggedId === targetId) return;

            const draggedComponent = findComponent(draggedId);
            const targetComponent = findComponent(targetId);
            if (!draggedComponent || !targetComponent) return;

            // Prevent dropping a parent into its own child
            let temp = targetComponent;
            while(temp = findParent(temp.id)) {
                if (temp.id === draggedId) return;
            }

            // Remove from old parent
            const oldParent = findParent(draggedId);
            const sourceList = oldParent ? oldParent.children : project.components;
            const index = sourceList.findIndex(c => c.id === draggedId);
            if (index > -1) sourceList.splice(index, 1);
            
            // Add to new parent
            targetComponent.children.push(draggedComponent);
            
            // Update positioning based on new parent
            if (targetComponent.style.display === 'flex') {
                draggedComponent.style.position = 'relative';
                delete draggedComponent.style.left;
                delete draggedComponent.style.top;
            } else {
                draggedComponent.style.position = 'absolute';
                draggedComponent.style.left = '10px';
                draggedComponent.style.top = '10px';
            }

            renderAll();
        });
    }

    function showContextMenu(event, componentId) {
        contextMenu.style.display = 'block';
        contextMenu.style.left = `${event.clientX}px`;
        contextMenu.style.top = `${event.clientY}px`;
        contextMenuTargetId = componentId;
        
        contextMenu.innerHTML = `
            <div data-action="add" data-type="div"><i class="fas fa-square-full mr-2"></i> Add Div</div>
            <div data-action="add" data-type="text"><i class="fas fa-font mr-2"></i> Add Text</div>
            <div data-action="add" data-type="button"><i class="fas fa-mouse-pointer mr-2"></i> Add Button</div>
            <hr class="my-1 border-gray-600">
            <div data-action="delete"><i class="fas fa-trash-alt mr-2 text-red-500"></i> Delete</div>
        `;
    }

    contextMenu.addEventListener('click', e => {
        const target = e.target.closest('div[data-action]');
        if (!target) return;
        
        const { action, type } = target.dataset;
        if (action === 'add') {
            createComponent(type, contextMenuTargetId);
        } else if (action === 'delete') {
            deleteComponent(contextMenuTargetId);
            if (selectedComponentId === contextMenuTargetId) selectedComponentId = null;
            renderAll();
        }
        contextMenu.style.display = 'none';
    });

    document.addEventListener('click', () => { contextMenu.style.display = 'none'; });

    // --- Global Event Listeners for Toolbar Drag ---
    toolbar.addEventListener('dragstart', e => {
        dragData.sourceType = e.target.dataset.type;
        dragData.isNew = true;
        e.dataTransfer.setData('text/plain', e.target.dataset.type);
    });
    
    canvas.addEventListener('dragover', e => e.preventDefault());

    canvas.addEventListener('drop', e => {
        e.preventDefault();
        if (!dragData.isNew) return;

        const type = e.dataTransfer.getData('text/plain');
        const targetWrapper = e.target.closest('.component-wrapper');
        const parentId = targetWrapper ? targetWrapper.dataset.id : null;
        
        createComponent(type, parentId);
        dragData = {};
    });

    propertiesPanel.addEventListener('input', e => {
        const component = findComponent(selectedComponentId);
        if (!component) return;
        
        const target = e.target;
        const { prop, style } = target.dataset;
        let value = target.type === 'checkbox' ? target.checked : target.value;
        
        if (prop) {
            component[prop] = value;
            if (prop === 'name') {
                document.querySelector(`.component-item[data-id="${selectedComponentId}"] span`).textContent = value;
                document.getElementById(selectedComponentId).dataset.name = value;
            }
        } else if (style) {
            if (!component.style) component.style = {};
            component.style[style] = value;
            if (style === 'display' && value === 'flex') {
                component.children.forEach(child => {
                    child.style.position = 'relative';
                    delete child.style.left;
                    delete child.style.top;
                });
                renderAll();
            } else {
                const el = document.getElementById(selectedComponentId);
                if (el) el.style[style] = value;
            }
        }
    });
    
    propertiesPanel.addEventListener('click', e => {
        if (e.target.id === 'delete-btn' && selectedComponentId) {
            deleteComponent(selectedComponentId);
            selectedComponentId = null;
            renderAll();
        }
    });

    // --- API Communication ---
    globalCssEditor.addEventListener('input', e => { project.globalCss = e.target.value; });
    globalJsEditor.addEventListener('input', e => { project.globalJs = e.target.value; });
    elementCssEditor.addEventListener('input', e => { if (selectedComponentId) project.elementCss[selectedComponentId] = e.target.value; });
    elementJsEditor.addEventListener('input', e => { if (selectedComponentId) project.elementJs[selectedComponentId] = e.target.value; });
    
    async function handleApiCall(apiPromise) {
        try {
            const result = await apiPromise;
            if (result.status === 'success') {
                if (result.data) {
                    project = result.data;
                    globalCssEditor.value = project.globalCss || '';
                    globalJsEditor.value = project.globalJs || '';
                    elementCssEditor.value = '';
                    elementJsEditor.value = '';
                    selectedComponentId = null;
                    renderAll();
                }
                if (result.message) console.info(result.message);
            } else {
                console.error(`API Error: ${result.message}`);
            }
        } catch (e) {
            console.error(`API Exception: ${e}`);
        }
    }

    importBtn.addEventListener('click', () => handleApiCall(window.pywebview.api.import_html()));
    exportBtn.addEventListener('click', () => handleApiCall(window.pywebview.api.export_html(project)));
    saveLuaBtn.addEventListener('click', () => handleApiCall(window.pywebview.api.save_lua(project)));
    saveProjectBtn.addEventListener('click', () => handleApiCall(window.pywebview.api.save_project(project)));
    loadBtn.addEventListener('click', () => handleApiCall(window.pywebview.api.load_project()));

    // --- Panel Resizing & Toggling Logic ---
    const panels = {
        elements: document.getElementById('elements-panel'),
        hierarchy: document.getElementById('hierarchy-panel-container'),
        properties: document.getElementById('properties-panel-container'),
        bottom: document.getElementById('bottom-editors')
    };
    const panelSizes = { elements: 224, hierarchy: 288, properties: 384, bottom: 40 };

    function updateGridLayout() {
        mainLayout.style.gridTemplateColumns = [
            panels.elements.style.display === 'none' ? '0px' : `${panelSizes.elements}px`,
            panels.elements.style.display === 'none' ? '0px' : '5px',
            panels.hierarchy.style.display === 'none' ? '0px' : `${panelSizes.hierarchy}px`,
            panels.hierarchy.style.display === 'none' ? '0px' : '5px',
            '1fr',
            panels.properties.style.display === 'none' ? '0px' : '5px',
            panels.properties.style.display === 'none' ? '0px' : `${panelSizes.properties}px`,
        ].join(' ');
    }

    function togglePanel(panelName) {
        const panel = panels[panelName];
        panel.style.display = panel.style.display === 'none' ? '' : 'none';
        updateGridLayout();
    }
    
    toggleElementsBtn.addEventListener('click', () => togglePanel('elements'));
    toggleHierarchyBtn.addEventListener('click', () => togglePanel('hierarchy'));
    togglePropertiesBtn.addEventListener('click', () => togglePanel('properties'));

    function initResizer(resizerId, panelKey, direction) {
        const resizer = document.getElementById(resizerId);
        resizer.addEventListener('mousedown', e => {
            e.preventDefault();
            document.body.style.cursor = direction === 'col' ? 'col-resize' : 'row-resize';
            
            let startPos = direction === 'col' ? e.clientX : e.clientY;
            
            const onMouseMove = moveEvent => {
                const movePos = direction === 'col' ? moveEvent.clientX : moveEvent.clientY;
                const delta = movePos - startPos;

                if (direction === 'col') {
                    const currentSize = panelSizes[panelKey];
                    const newSize = panelKey === 'properties' ? currentSize - delta : currentSize + delta;
                    panelSizes[panelKey] = Math.max(150, newSize);
                    updateGridLayout();
                } else { // row
                    const currentHeight = panelSizes[panelKey];
                    const newHeight = currentHeight - (delta / window.innerHeight * 100);
                    panelSizes[panelKey] = Math.max(10, Math.min(80, newHeight));
                    document.getElementById('canvas-section').style.gridTemplateRows = `1fr 5px ${panelSizes.bottom}%`;
                }
                startPos = movePos;
            };
            
            const onMouseUp = () => {
                document.body.style.cursor = 'default';
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            };
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }

    initResizer('resizer-v1', 'elements', 'col');
    initResizer('resizer-v2', 'hierarchy', 'col');
    initResizer('resizer-v3', 'properties', 'col');
    initResizer('resizer-h1', 'bottom', 'row');

    // --- Initial Render ---
    renderAll();
});
