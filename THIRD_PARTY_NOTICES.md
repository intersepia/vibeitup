# Third-party notices

The viewer ships two vendored browser libraries so it works fully offline:

| Library | Version | License | File |
| --- | --- | --- | --- |
| [Vue.js](https://vuejs.org/) | 3.5.44 | MIT | `src/vibegraph/static/vendor/vue.global.prod.js` |
| [D3.js](https://d3js.org/) | 7.9.0 | ISC | `src/vibegraph/static/vendor/d3.min.js` |

The corresponding license texts are included next to the files:

- `src/vibegraph/static/vendor/VUE-LICENSE`
- `src/vibegraph/static/vendor/D3-LICENSE`

No network requests are made by the viewer; all assets are served locally.
