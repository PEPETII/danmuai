// The old browser compiler replaced the early window.tailwind.config object.
// Preserve its observed default utilities; warm-tokens CSS owns product colors.
module.exports = {
  content: [
    './web/static/index.template.html',
    './web/static/partials/**/*.html',
    './web/static/app.js',
    './web/static/modules/**/*.js',
  ],
};
