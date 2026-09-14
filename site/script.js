(function () {
  var targets = document.querySelectorAll(".reveal");

  if (!("IntersectionObserver" in window) || !targets.length) {
    targets.forEach(function (el) { el.classList.add("in-view"); });
    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15 }
  );

  targets.forEach(function (el) { observer.observe(el); });
})();
