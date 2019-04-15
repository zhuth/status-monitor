Vue.component('button-toggler', {
    props: ['node', 'val', 'action'],
    template: `
	<button class="mui-btn mui-btn--fab" :data-action="action" :data-node="node || 'self'"
				  :v-if="typeof(val) !== 'undefined'"
				  :class="{ 'button-on': val === true, 'button-off': val === false }">
			  {{ val ? '开' : '关' }}</button>
			  `
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


(function() {

    var app = new Vue({
        el: '#app',
        data: {
            config: config,
            nodes: [],
            switch_nodes: [],
            services: [],
            videos: [],
            resp: {},
            services: [],
            current: [''],
            output: ''
        },
        methods: {
            load_services: function() {
                app.services = [];
                $.get('node/' + app.current[1] + '/services').done((data) => {
                    app.services = data.resp;
                });
            },
            navigate: function(u) {
                location.hash = '#' + u;
            },
            load_all_services: function() {
                app.services = [];
                $.get('node/self/all_services').done((data) => {
                    app.services = data.resp;
                });
            }
        }
    });
    jQuery(function($) {
        const
            $bodyEl = $('body'),
            $main = $('#u_main'),
            $sidedrawer = $('#sidedrawer');

        $.get('node/self').done((data) => {
            app.nodes.push('self');
            for (let node in data.resp.nodes) {
                if (['SwitchNode', 'KonkeNode'].indexOf(data.resp.nodes[node]) >= 0) {
                    app.switch_nodes.push(node);
                } else {
                    app.nodes.push(node);
                }
            }
            if (app.switch_nodes.length > 0) {
                app.nodes.push('switches');
            }
        });

        function update() {
            if (app.current[0] === 'video') {
                $main.find('img[alt="video"]').attr('src',
                    app.config.video_provider.replace('{channel}', app.current[1]).replace('{t}', Math.random())
                );
            } else {
                var nodes = app.nodes;
                if (app.current[1] === 'switches') nodes = app.switch_nodes;
                else if (app.current[0] === 'node') nodes = [app.current[1]];

                for (let n of nodes) {
                    $.get('node/' + n).done((data) => {
                        app.resp[n] = data.resp;
                        app.$forceUpdate();
                    });
                }
                app.$forceUpdate();
            }
        }

        $(window).on('hashchange', function(e) {
            const
                $this = $(this),
                hash = location.hash.substr(1).split('/');

            app.current = hash;
            app.services = [];
            app.output = '';
            if (hash[0] == 'services') app.load_all_services();
            update();
        });

        $(document).on('click', 'button[data-action]', function() {
            const $this = $(this);
            var node = $this.data('node') || app.current[1];
            var action = $this.data('action');
            if ($this.attr('disabled')) return;
            $this.attr('disabled', 'disabled');

            switch (action) {
                case 'toggle_power':
                    action = 'power_' + ($this.hasClass('button-on') ? 'off' : 'on');
                    break;
                case 'toggle_service':
                    action = 'set_service/' + $this.data('service') + ($this.hasClass('button-on') ? '/stop' : '/start');
                    break;
                case 'link':
                    location.href = $this.data('href');
                    return;
                default:
                    break;
            }

            if (action) {
                $.get('node/' + node + '/' + action)
                    .done((data) => {
                        if (data.error) alert(data.error);
                        if (data.resp && data.resp.output) app.output = data.resp.output;
                    })
                    .then(() => {
                        update();
                        $this.removeAttr('disabled');
                    });
            }
        });

        $('section').hide();
        if (location.hash === '') location.hash = 'node/' + app.config.default_node;
        else $(window).trigger('hashchange');

        setInterval(update, 5000);


        (function() { // side drawer
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
    });
})();