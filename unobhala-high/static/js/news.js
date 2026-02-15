document.addEventListener("DOMContentLoaded", () => {

    // SEE MORE / LESS
    document.querySelectorAll(".see-more").forEach(btn => {
        btn.addEventListener("click", () => {
            const id = btn.dataset.post;
            const text = document.getElementById("text-" + id);

            text.classList.toggle("collapsed");
            btn.textContent = text.classList.contains("collapsed")
                ? "See more"
                : "See less";
        });
    });

    // IMAGE SLIDER
    document.querySelectorAll(".slider").forEach(slider => {
        const postId = slider.dataset.post;
        const imgEl = slider.querySelector(".slider-img");
        const data = document.getElementById("images-" + postId);

        if (!data) return;

        const images = JSON.parse(data.textContent);
        let index = 0;

        const left = slider.querySelector(".left");
        const right = slider.querySelector(".right");

        if (left) {
            left.addEventListener("click", () => {
                index = (index - 1 + images.length) % images.length;
                imgEl.src = "/static/" + images[index];
            });
        }

        if (right) {
            right.addEventListener("click", () => {
                index = (index + 1) % images.length;
                imgEl.src = "/static/" + images[index];
            });
        }
    });

});
