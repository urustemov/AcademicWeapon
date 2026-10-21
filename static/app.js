(() => {
 const toggle = document.getElementById('themeToggle');
 if(toggle) toggle.addEventListener('click',()=>{const current=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=current;try{localStorage.setItem('apss_theme',current)}catch(e){}});
 const menu=document.getElementById('menuBtn'),aside=document.getElementById('sidebar'),screen=document.getElementById('mobileScreen');
 function close(){if(aside)aside.classList.remove('mobile-open');if(screen)screen.classList.remove('show')}
 if(menu)menu.addEventListener('click',()=>{aside.classList.toggle('mobile-open');screen.classList.toggle('show')});
 if(screen)screen.addEventListener('click',close);
 document.querySelectorAll('.main-nav a').forEach(link=>link.addEventListener('click',close));
 document.querySelectorAll('[data-email][data-password]').forEach(button=>button.addEventListener('click',()=>{
  const email=document.getElementById('email'),pass=document.getElementById('password');
  if(email)email.value=button.dataset.email;if(pass)pass.value=button.dataset.password;
  document.querySelectorAll('.demo-account').forEach(x=>x.classList.remove('selected'));button.classList.add('selected');
  if(pass)pass.focus();
 }));
})();
