/* ===================================================== */
/*                 FUNÇÃO HASH → COR                    */
/* ===================================================== */
/* Gera uma cor única e estável para cada tag */
function hashColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    let color = "#";
    for (let i = 0; i < 3; i++) {
        color += ("00" + ((hash >> (i * 8)) & 0xFF).toString(16)).slice(-2);
    }
    return color;
}


/* ===================================================== */
/*           PREVIEW AUTOMÁTICO DE TAGS                 */
/* ===================================================== */

function setupTagPreview() {
    const input = document.querySelector('input[name="tags"]');
    const preview = document.querySelector("#tag-preview");

    if (!input || !preview) return;

    function render() {
        preview.innerHTML = "";

        const tags = input.value
            .split(",")
            .map(t => t.trim())
            .filter(t => t.length > 0);

        tags.forEach(t => {
            const span = document.createElement("span");
            span.classList.add("tag-chip");
            span.style.backgroundColor = hashColor(t.toUpperCase());
            span.textContent = t.toUpperCase();
            preview.appendChild(span);
        });
    }

    input.addEventListener("input", render);
    render();
}

document.addEventListener("DOMContentLoaded", setupTagPreview);


/* ===================================================== */
/*     CONFIRMAÇÕES DE SEGURANÇA (EXCLUIR / RESTAURAR)  */
/* ===================================================== */

function confirmarExclusao() {
    return confirm("Deseja realmente excluir este registro?");
}

function confirmarRestaurar() {
    return confirm("Deseja restaurar este registro?");
}


/* ===================================================== */
/*   Mostra/esconde senha no login (compatível futuro)   */
/* ===================================================== */

function togglePassword(idInput, idIcon) {
    let input = document.getElementById(idInput);
    let icon = document.getElementById(idIcon);

    if (!input) return;

    if (input.type === "password") {
        input.type = "text";
        if (icon) icon.textContent = "🙈";
    } else {
        input.type = "password";
        if (icon) icon.textContent = "👁️";
    }
}


/* ===================================================== */
/*             MARCAR TODOS (checkbox geral)            */
/* ===================================================== */

function toggleCheckAll(masterId, groupName) {
    let master = document.getElementById(masterId);
    let boxes = document.querySelectorAll("input[name='" + groupName + "']");

    boxes.forEach(b => (b.checked = master.checked));
}
