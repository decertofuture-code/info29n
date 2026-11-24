// Modo claro / oscuro: se aplica antes de pintar la página y se recuerda en este navegador.
(function(){
  var raiz=document.documentElement, CLAVE="info29n-tema";
  try{var t=localStorage.getItem(CLAVE);if(t==="light"||t==="dark")raiz.dataset.theme=t;}catch(e){}
  function oscuro(){return raiz.dataset.theme?raiz.dataset.theme==="dark":matchMedia("(prefers-color-scheme: dark)").matches;}
  function pintar(){
    var o=oscuro();
    document.querySelectorAll(".js-modo").forEach(function(b){
      b.setAttribute("aria-label",o?"Cambiar a modo claro":"Cambiar a modo oscuro");
      b.setAttribute("title",o?"Modo claro":"Modo oscuro");
    });
    var m=document.querySelector('meta[name="theme-color"]');if(m)m.content=o?"#1A222E":"#FFFFFF";
  }
  function cambiar(){
    raiz.dataset.theme=oscuro()?"light":"dark";
    try{localStorage.setItem(CLAVE,raiz.dataset.theme);}catch(e){}
    pintar();
  }
  document.addEventListener("click",function(e){if(e.target.closest&&e.target.closest(".js-modo"))cambiar();});
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change",pintar);
  document.addEventListener("DOMContentLoaded",pintar);
})();
