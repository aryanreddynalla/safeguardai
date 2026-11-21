(function(){
var d=document,b=d.body,w=d.createElement('div');
w.innerHTML='<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><filter id="lg" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB"><feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves="2" seed="7" result="n"/><feGaussianBlur in="n" stdDeviation="3" result="m"/><feDisplacementMap in="SourceGraphic" in2="m" scale="64" xChannelSelector="R" yChannelSelector="G" result="a"/><feColorMatrix in="a" type="matrix" values="1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0" result="r"/><feDisplacementMap in="SourceGraphic" in2="m" scale="70" xChannelSelector="R" yChannelSelector="G" result="b"/><feColorMatrix in="b" type="matrix" values="0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 1 0" result="g"/><feDisplacementMap in="SourceGraphic" in2="m" scale="76" xChannelSelector="R" yChannelSelector="G" result="c"/><feColorMatrix in="c" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 1 0" result="bl"/><feBlend in="r" in2="g" mode="screen" result="rg"/><feBlend in="rg" in2="bl" mode="screen"/></filter></defs></svg>';
b.prepend(w.firstChild);
var bg=d.createElement('div');bg.className='glass-bg';bg.innerHTML='<i></i><i></i><i></i>';b.prepend(bg);
if(window.chrome){d.querySelectorAll('.panel,.stat-card,.notice-banner').forEach(function(el){var f='url(#lg) blur(8px) saturate(150%)';el.style.backdropFilter=f;el.style.webkitBackdropFilter=f;});}
d.querySelectorAll('.stat-card').forEach(function(el){
el.addEventListener('pointermove',function(e){var r=el.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;el.style.transform='perspective(800px) rotateX('+(-y*8)+'deg) rotateY('+(x*8)+'deg) scale(1.02)';});
el.addEventListener('pointerleave',function(){el.style.transform='';});});
var h=d.querySelector('.hero-glass'),s=d.getElementById('stage');
if(h&&s){h.addEventListener('pointermove',function(e){var r=h.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;s.style.transform='rotateY('+(x*22)+'deg) rotateX('+(-y*16)+'deg)';});h.addEventListener('pointerleave',function(){s.style.transform='';});}
})();
