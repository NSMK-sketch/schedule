document.getElementById("setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const form = event.currentTarget;
    const error = document.getElementById("setup-error");
    const button = form.querySelector("button[type='submit']");
    error.classList.add("hidden");

    const payload = {
        username: document.getElementById("setup-username").value.trim(),
        password: document.getElementById("setup-password").value,
        password_confirm: document.getElementById("setup-password-confirm").value,
        max_bot_token: document.getElementById("setup-token").value.trim(),
        public_url: document.getElementById("setup-public-url").value.trim(),
    };

    button.disabled = true;
    try {
        const response = await fetch("/api/setup", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            error.textContent = data.error || "Не удалось завершить установку.";
            error.classList.remove("hidden");
            button.disabled = false;
            return;
        }
        window.location.href = "/admin";
    } catch (err) {
        error.textContent = "Нет связи с сервером.";
        error.classList.remove("hidden");
        button.disabled = false;
    }
});
