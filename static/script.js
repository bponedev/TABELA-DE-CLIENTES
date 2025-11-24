// hashColor stable
function hashColor(str){
    let hash = 0;
    for(let i=0;i<str.length;i++){ hash = str.charCodeAt(i) + ((hash<<5) - hash); }
    let color = "#";
    for(let i=0;i<3;i++){ color += ("00" + ((hash >> (i*8)) & 0xFF).toString(16)).slice(-2); }
    return color;
}

function setupTagPreview(){
    const input = document.querySelector('input[name="tags"]');
    const preview = document.querySelector('#tag-preview');
    if(!input || !preview) return;
    function render(){
        preview.innerHTML = '';
        const tags = input.value.split(',').map(t=>t.trim()).filter(t=>t.length);
        tags.forEach(t=>{
            const span = document.createElement('span');
            span.className='tag-chip';
            span.style.backgroundColor = hashColor(t.toUpperCase());
            span.textContent = t.toUpperCase();
            preview.appendChild(span);
        });
    }
    input.addEventListener('input', render);
    render();
}
document.addEventListener('DOMContentLoaded', setupTagPreview);

// toggle password
function togglePassword(idInput, idIcon){
    let input = document.getElementById(idInput);
    let icon = document.getElementById(idIcon);
    if(!input) return;
    if(input.type === 'password'){ input.type = 'text'; if(icon) icon.textContent='🙈'; }
    else{ input.type = 'password'; if(icon) icon.textContent='👁️'; }
}

// toggleSelectAll for table checkboxes
function toggleSelectAll(master){
    const boxes = document.querySelectorAll('input[name="ids"]');
    boxes.forEach(b => b.checked = master.checked);
}
