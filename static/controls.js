String.prototype.format = function (o) {
    var r = this;
    if (this.match(/\{\{.*?\}\}/)) {
        r = r.replace(/\{\{(.*?)\}\}/g, function (x, g) { return g.feval(o); });
    }
    return r.replace(/\{([a-zA-Z0-9\_\.]+)\}/g, function (x, g) {
        g = g.split('.');
        var oo = o;
        for (var k of g) {
            if (typeof (oo[k]) === 'undefined') return '{' + g.join('.') + '}';
            oo = oo[k];
        }
        return oo;
    });
};

String.prototype.feval = function (o) {
    for (var k in o)
        eval("var " + k + "=(" + JSON.stringify(o[k]) + ")");

    return eval("(" + this + ")");
};


jQuery(function ($) {
    const
        $bodyEl = $('body'),
        $main = $('#u_main'),
        $sidedrawer = $('#sidedrawer'),
        $services = $('#u_services ul'),
        $nodes = $('#u_nodes ul');

    var switch_nodes = [];
    var current_node = '';
    var current_function = '';
    var interval_functions = {
        '': function () { },
        'node': function () {
            if (current_node == 'switches') {
                for (let n of switch_nodes) {
                    $.get('node/' + n.node).done((data) => {
                        render_object(data.resp, data.node);
                    });
                }
            } else {
                $.get('node/' + current_node).done((data) => {
                    if (data.node !== current_node) return;
                    render_object(data.resp);
                });
            }
        },
        'services': function () {
            $('#u_nodes a').each((i, x) => {
                const $x =$(x);
                if ($x.attr('href') == '#node/switches') return;
                const node = $x.attr('href').split('/')[1];
                $.get('node/' + node).done((data) =>{
                    render_object(data.resp.services, data.node);
                });
            });
        },
		'video': function () {
            $main.find('img[alt="video"]').attr('src', config.video_provider.format({ 'node': location.hash.split('/')[1], 't': Math.random() }));			
		}
    };

    function render_object(o, name) {
        if (o && o.temp) o.temp = o.temp.replace(/(\d+)d/g, '$1°C');
        name = name || '';
        let disp = $main.find('#n_' + name);
        if (disp.length == 0 && typeof (o) !== 'object') return;

        switch (typeof (o)) {
            case "object":
                for (var k in o)
                    render_object(o[k], (name ? (name + '_') : '') + k);
                break;
            case "boolean":
                if (disp[0].tagName === 'BUTTON') {
                    disp.removeClass('button-on').removeClass('button-off').addClass(o ? 'button-on' : 'button-off');
                }
                disp.html(o ? '开' : '关');
                break;
            default:
                if (disp[0].tagName === 'IMG')
                    disp.attr('src', o)
                else
                    disp.html(o);
                break;
        }
    }

    function resolve_for_tags(bundle, ele) {
        ele = ele || $main;
        ele.children('for').each((i, x) => {
            var $x = $(x);
            const loop_id = '__t' + new Date().valueOf();
            const array = $x.attr('array') || $x.attr('dict'),
                kvar = $x.attr('keyvar') || ('key' + loop_id),
                vvar = $x.attr('valvar') || ('val' + loop_id),
                tag = $x.attr('wrapper') || 'div',
                ifcond = $x.attr('if') || '';
            var obj = bundle[array] || array.feval(bundle);
            const t = $x.html();
            var p = $x.parent();
            $x.replaceWith('<{tag} class="{loop_id}"></{tag}>'.format({ 'tag': tag, 'loop_id': loop_id }));
            $x = p.find('.' + loop_id);

            if (obj) {
                if (Array.isArray(obj)) {
                    var ob = {}, i = 0;
                    for (var a of obj) ob[i++] = a;
                    obj = ob;
                }
                for (var a in obj) {
                    var ob = {};
                    ob[kvar] = a; ob[vvar] = obj[a];
                    if (ifcond !== '' && !ifcond.feval(ob)) continue;
                    var el = t.format(ob);
                    $x.append('<span class="__iter">' + el + '</span>');
                    if ($x.children().last().children('for').length) {
                        resolve_for_tags(ob, $x.children().last());
                    }
                }
            }
        });
    }

    var templates = {};
    $('template').each((i, x) => {
        templates[$(x).attr('for')] = $(x).html();
        $(x).remove();
    });


    $.get('node/self').done((data) => {
        data.resp.nodes.self = 'StatusNode';
        for (let node in data.resp.nodes) {
            var name = (config.nodes || {})[node] || node;
            if (['SwitchNode', 'KonkeNode'].indexOf(data.resp.nodes[node]) >= 0) {
                switch_nodes.push({ 'node': node, 'name': name });
            } else {
                $nodes.append('<li><a href="#node/{node}">{name}</a></li>'.format({ 'node': node, 'name': name }));
            }
        }
        if (switch_nodes.length > 0) {
            $nodes.append('<li><a href="#node/{node}">{name}</a></li>'.format({ 'node': 'switches', 'name': (config.nodes || {})['switches'] || 'switches' }));
        }
    }).then(function () {
        $(window).on('hashchange', function (e) {
            const
                $this = $(this),
                hash = location.hash.substr(1).split('/');

            // find template
            var templ = hash.slice(0, 2).join('/'), name = (config.nodes || {})[hash[1]] || hash[1];
            if (templates[templ]) templ = templates[templ];
            else if (templates[hash[0]]) templ = templates[hash[0]];
            $main.html(templ);

            current_function = hash[0];
            if (!interval_functions[current_function]) current_function = '';

            switch (hash[0]) {
                case 'node':
                    current_node = hash[1];
                    resolve_for_tags({ 'switch_nodes': switch_nodes });
                    break;
                case 'video':
                    name = 'Video ' + hash[1];
                    break;
                case 'services':
                    name = '';
                    $.get('node/self/all_services').done((data) => resolve_for_tags(data));
                    break;
            }

            $('h1#n_name').text(name);

            interval_functions[current_function]();

            $('li.active', $sidedrawer).removeClass('active');
            $('a[href="' + location.hash + '"]', $sidedrawer).parent().addClass('active');
        });

        $(document).on('click', '[data-mui-controls="pane-node-services"]', function (e) {
            $.get('node/{node}/load_services'.format({ 'node': current_node })).done((data) => {
                resolve_for_tags(data, $('#pane-node-services'));
                interval_functions[current_function]();
            });
        }).on('click', 'button[data-action]', function () {
            const $this = $(this);
            var action = $this.data('action');
            if ($this.attr('disabled')) return;
            if (!$this.data('node')) $this.data('node', current_node);
            $this.attr('disabled', 'disabled');

            switch (action) {
                case 'toggle_power':
                    action = 'power_' + ($this.hasClass('button-on') ? 'off' : 'on');
                    break;
                case 'toggle_service':
                    action = 'set_service/' + $this.data('service') + ($this.hasClass('button-on') ? '/restart' : '/start');
                    break;
                case 'link':
                    location.href = $this.data('href');
                    break;
                default:
                    break;
            }

            if (action) {
                $.get('node/{node}/'.format($this.data()) + action)
                    .done((data) => {
                        if (data.error) alert(data.error);
                    })
                    .then(() => {
                        interval_functions[current_function]();
                        $this.removeAttr('disabled');
                    });
            }
        });

        if (location.hash === '') location.hash = 'node/' + config.default_node;
        else $(window).trigger('hashchange');

    });

    setInterval(function () {
        interval_functions[current_function]();
    }, 5000);

    (function () { // side drawer
        $('.js-show-sidedrawer').on('click', function () {
            var options = {
                onclose: function () {
                    $sidedrawer
                        .removeClass('active')
                        .appendTo(document.body);
                }
            };

            var $overlayEl = $(mui.overlay('on', options));
            $sidedrawer.appendTo($overlayEl);
            setTimeout(function () {
                $sidedrawer.addClass('active');
            }, 20);
        });

        $('.js-hide-sidedrawer').on('click', function () {
            $bodyEl.toggleClass('hide-sidedrawer');
        });

        $('strong', $sidedrawer).on('click', function () {
            $(this).next().slideToggle(200);
        }).next().hide();

        $('strong', $sidedrawer).first().click();
    })();
})