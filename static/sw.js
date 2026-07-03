// Service worker mínimo — existe só para o Chrome/Android considerar o app
// "instalável" (exige um fetch handler registrado). Não faz cache: o app
// depende de conexão ao vivo com o banco de dados, então cachear respostas
// aqui só causaria dados desatualizados.
self.addEventListener('fetch', function (event) {
  event.respondWith(fetch(event.request));
});
