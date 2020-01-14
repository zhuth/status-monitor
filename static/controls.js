(function() {

    const $ = jQuery,
        $get = $.get;

    Vue.component('button-toggler', {
        props: ['node', 'val', 'action', 'service'],
        data: function() {
            return {
                disabled: false
            }
        },
        template: `
		<button @click="toggle" class="mui-btn mui-btn--fab"
				:class="{ 'button-on': val === true, 'button-off': val === false }"
				:disabled="disabled"
				v-show="typeof(val) === 'boolean'">{{ val ? '开' : '关' }}
		</button>`,
        methods: {
            toggle() {
                var action = this.action;
                this.disabled = true;
                if (action === 'power') action += this.val ? '_off' : '_on';
                else if (action.substr(0, 7) === 'service') action = 'set_' + action + '/' + (this.val ? 'stop' : 'start');
                $get('node/' + this.node + '/' + action).then((data) => {
                    if (data.error) alert(data.error);
                }).then((error) => {
                    this.disabled = false;
                });
                this.$emit('click');
            }
        }
    });

    Vue.component('temperature-viewer', {
        props: ['val'],
        computed: {
            val_deg() {
                return (this.val || "").replace(/(\d+(\.\d+)?)d/g, "$1°C");
            }
        },
        template: `<span>{{ val_deg }}</span>`
    });

    var app = new Vue({
        el: '#app',
        data: {
            config: config,
            nodes: ['self'],
            switch_nodes: [],
            resp: {},
            current: [''],
            output: '',
            _t: 0
        },
        methods: {
            navigate(u) {
                location.hash = '#' + u;
            },
            action_button(node, action, param) {
                switch (action) {
                    case 'link':
                        location.href = param.link;
                        return;
                    default:
                        break;
                }

                if (action) {
                    $get('node/' + node + '/' + action)
                        .then((data) => {
                            if (data.error) alert(data.error);
                            if (data.resp && data.resp) this.output = data.resp;
                        })
                        .then(() => {
                            this.disabled = false;
                            this.update();
                        });
                }
            },
            update() {
                if (this.current[0] === 'cameras') {
                    this._t = Math.random();
                } else {
                    var nodes = this.nodes;
                    if (this.current[0] === 'switches') nodes = this.switch_nodes;
                    else if (this.current[0] === 'node') nodes = [this.current[1]];

                    for (let n of nodes) {
                        $get('node/' + n).then((data) => {
                            if (data.resp) this.resp[n] = data.resp;
                            this.$forceUpdate();
                        });
                    }
                }
                this.$forceUpdate();
            }
        }
    });

    $.get('node/self').then((data) => {
        for (let node in data.resp.nodes) {
            if (['SwitchNode', 'KonkeNode'].indexOf(data.resp.nodes[node]) < 0) app.nodes.push(node);
            else app.switch_nodes.push(node);
        }
    });

    $(window).on('hashchange', function(e) {
        const
            hash = location.hash.substr(1).split('/');

        app.current = hash;
        app.output = '';
        app.update();
    });

    if (location.hash === '') location.hash = '#' + config.default_hash;
    else $(window).trigger('hashchange');

    setInterval(app.update, 5000);

    (function() { // side drawer

        const
            $bodyEl = $('body'),
            $sidedrawer = $('#sidedrawer');

        $('.js-show-sidedrawer').on('click', function() {
            var options = {
                onclose: function() {
                    $sidedrawer
                        .removeClass('active')
                        .appendTo(document.body);
                }
            };

            var $overlayEl = $(mui.overlay('on', options));
            $sidedrawer.appendTo($overlayEl);
            setTimeout(function() {
                $sidedrawer.addClass('active');
            }, 20);
        });

        $('.js-hide-sidedrawer').on('click', function() {
            $bodyEl.toggleClass('hide-sidedrawer');
        });

        $('strong', $sidedrawer).on('click', function() {
            $(this).next().slideToggle(200);
        }).next().hide();

        $('strong', $sidedrawer).first().click();
    })();

})();
