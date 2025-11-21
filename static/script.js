/* =======================================================
   SCRIPT GERAL — TAGS, MENU, FUNCIONALIDADES GLOBAIS
========================================================= */

/* ----------------------------------------------
   Função de hash → gera cor consistente p/ TAGS
---------------------------------------------- */
function hashColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    let color = '#';
    for (let i = 0; i < 3; i++) {
        color += ('00' + ((hash >> (i * 8)) & 0xFF).toString(16)).slice(-2);
    }
    return color;
}


/* ----------------------------------------------
   Preview automático de TAGS na criação
---------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
    const tagInput = document.querySelector('input[name="tags"]');
    const preview = document.querySelector('#tag-preview');

    if (tagInput && preview) {

        function renderPreview() {
            preview.innerHTML = "";

            const tags = tagInput.value.split(",")
                .map(t => t.trim())
                .filter(t => t.length > 0);

            tags.forEach(t => {
                const chip = document.createElement("span");
                chip.classList.add("tag-chip");
                chip.style.backgroundColor = hashColor(t.toUpperCase());
                chip.textContent = t.toUpperCase();
                preview.appendChild(chip);
            });
        }

        tagInput.addEventListener("input", renderPreview);
        renderPreview();
    }
});


/* ------------------------------------------------
   Exibir senha (login)
-------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("toggle-pass");
    const field = document.getElementById("password");

    if (btn && field) {
        btn.addEventListener("click", () => {
            field.type = field.type === "password" ? "text" : "password";
            btn.innerText = field.type === "password" ? "Mostrar" : "Ocultar";
        });
    }
});
