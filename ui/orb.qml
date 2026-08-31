/* ══════════════════════════════════════════════════════════════════════
   ЯДРО НА СТОЛЕ — НАТИВНЫЙ ВИДЖЕТ (2026-08-23)

   Владелец, посмотрев на первую версию: «выглядит как всратая png… нельзя
   её сделать красивым интерактивным виджетом, с прозрачностью и
   анимациями». Первая версия показывала в окне ту же страницу, что и
   большой экран, — и тащила за собой весь браузерный движок вместе с его
   болезнью: прозрачность безрамочного окна с QWebEngineView на Windows
   не гарантирована, и вместо ядра на столе появлялся чёрный прямоугольник.

   Здесь браузера нет вообще. Рисует сам Qt: у окна QML прозрачность —
   штатная вещь, а не борьба. Взамен визуал написан заново, но написан по
   тем же правилам, что и ядро на большом экране, — это тот же предмет,
   а не его двойник:
     · шар со светом сверху и вырезанным именем;
     · дуги органов: пустой контур виден всегда (место органа не исчезает
       вместе с ним), залитая часть — готовность, мигает при загрузке,
       краснеет при поломке;
     · полосы звука: наружу — что слышит, внутрь — что говорит;
     · дыхание в покое, поворот кольца при раздумье, свечение при речи.

   Всё, что здесь показано, приходит от сервера (см. tools/orb_qml.py).
   Ни одного выдуманного числа: нечего показать — ничего и не рисуем.
   ══════════════════════════════════════════════════════════════════════ */
import QtQuick

Item {
    id: root
    anchors.fill: parent
    property real u: Math.min(width, height)

    // ── что приходит снаружи ──
    property var bandsOut: []          // что слышит
    property var bandsInn: []          // что говорит
    property var organs: ({})          // hear/voice/brain/eyes/face/hands
    property string mood: "idle"       // idle | hear | think | talk
    property bool alive: true          // сервер отвечает

    // ── собственная жизнь ──
    property real breath: 1.0
    property real spin: 0
    property real talkGlow: 0
    property bool hovered: false
    property bool held: false
    property real appear: 0

    opacity: appear
    scale: 0.72 + 0.28 * appear
    Component.onCompleted: appearAnim.start()
    NumberAnimation { id: appearAnim; target: root; property: "appear"
        from: 0; to: 1; duration: 420; easing.type: Easing.OutBack }

    /* Дыхание — 4.6 с, спокойный вдох-выдох человека. Виджет живёт на
       чужом рабочем столе и не имеет права отвлекать: движение мелкое. */
    SequentialAnimation on breath {
        loops: Animation.Infinite; running: !root.hovered
        NumberAnimation { to: 1.022; duration: 2300; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.0;   duration: 2300; easing.type: Easing.InOutSine }
    }
    /* Раздумье видно поворотом кольца: ожидание должно быть видно, иначе
       тишина читается как «повисло». */
    NumberAnimation on spin {
        from: 0; to: 360; duration: 7000; loops: Animation.Infinite
        running: root.mood === "think"
    }
    SequentialAnimation on talkGlow {
        loops: Animation.Infinite; running: root.mood === "talk"
        NumberAnimation { to: 1; duration: 420; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 520; easing.type: Easing.InOutSine }
    }

    Canvas {
        id: cv
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative
        antialiasing: true

        Timer { interval: 33; running: true; repeat: true; onTriggered: cv.requestPaint() }

        function ring(ctx, cx, cy, r, a0, a1, lw, style) {
            ctx.lineWidth = lw; ctx.strokeStyle = style;
            ctx.beginPath(); ctx.arc(cx, cy, r, a0, a1); ctx.stroke();
        }

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var w = width, h = height, cx = w / 2, cy = h / 2, u = root.u;
            var rs = u * 0.170 * root.breath                 // радиус шара
                     * (root.held ? 0.95 : (root.hovered ? 1.06 : 1.0));
            /* РАЗНЫЕ ВЕЩИ — РАЗНЫЕ ПОЯСА (2026-08-23, первый прогон на
               стенде: риски и полосы стояли в одном кольце и слипались в
               мех — рисунок есть, звука в нём не видно). Порядок от
               центра: шар, узкий поясок рисок, полосы звука, дуги
               органов. Каждому своё место, и ничто ни на что не лезет. */
            var R  = u * 0.232;                              // где стоят полосы
            var L  = u * 0.098;                              // их длина
            var rA = u * 0.375;                              // дуги органов
            var dim = root.alive ? 1 : 0.45;                 // сервер молчит

            // ── 1. ОРЕОЛ. Мягкое свечение снизу-вокруг: без него предмет
            //    лежит на столе как наклейка, с ним — стоит над ним.
            var halo = ctx.createRadialGradient(cx, cy, rs * 0.6, cx, cy, u * 0.5);
            var hi = (root.hovered ? 0.12 : 0.07) + root.talkGlow * 0.10;
            halo.addColorStop(0, "rgba(255,255,255," + (hi * dim) + ")");
            halo.addColorStop(0.55, "rgba(190,205,235," + (hi * 0.35 * dim) + ")");
            halo.addColorStop(1, "rgba(0,0,0,0)");
            ctx.fillStyle = halo;
            ctx.beginPath(); ctx.arc(cx, cy, u * 0.5, 0, Math.PI * 2); ctx.fill();

            // ── 2. ДУГИ ОРГАНОВ. Порядок и углы те же, что на большом
            //    экране: глаза сверху, руки внизу — объяснимое запоминается.
            var order = [["eyes", -90], ["brain", -30], ["hands", 30],
                         ["voice", 90], ["hear", 150], ["face", -150]];
            var span = 52, lw = Math.max(2.4, u * 0.016);
            ctx.lineCap = "butt";
            for (var i = 0; i < order.length; i++) {
                var key = order[i][0];
                var mid = order[i][1] + root.spin;
                var a0 = (mid - span / 2) * Math.PI / 180;
                var a1 = (mid + span / 2) * Math.PI / 180;
                var o = root.organs[key] || {};
                var st = o.state || "off";
                // пустой контур виден всегда: «выключено» и «его тут нет»
                // не должны выглядеть одинаково
                ring(ctx, cx, cy, rA, a0, a1, lw, "rgba(255,255,255," + (0.11 * dim) + ")");
                var v = st === "ready" ? 1 : (st === "loading" ? 0.55
                        : (st === "broken" ? 0.30 : 0));
                if (v <= 0.004) continue;
                var col = "255,255,255", al = 0.92;
                if (st === "loading") {
                    al = 0.38 + 0.5 * (0.5 + 0.5 * Math.sin(Date.now() / 280));
                } else if (st === "broken") {
                    col = "224,101,95"; al = 0.95;   // поломка видна цветом
                }
                ring(ctx, cx, cy, rA, a0, a0 + (a1 - a0) * v, lw,
                     "rgba(" + col + "," + (al * dim) + ")");
            }

            // ── 3. РИСКИ вокруг шара — мелкая шкала, по которой глаз ловит
            //    поворот и масштаб. Своего смысла не несёт и не притворяется.
            ctx.lineCap = "butt";
            ctx.lineWidth = Math.max(0.6, u * 0.0032);
            for (var t = 0; t < 60; t++) {
                var ta = (t / 60) * Math.PI * 2 - Math.PI / 2;
                var big = (t % 5 === 0);
                var r0 = rs + u * 0.010, r1 = r0 + u * (big ? 0.020 : 0.010);
                ctx.strokeStyle = "rgba(255,255,255," + ((big ? 0.22 : 0.10) * dim) + ")";
                ctx.beginPath();
                ctx.moveTo(cx + Math.cos(ta) * r0, cy + Math.sin(ta) * r0);
                ctx.lineTo(cx + Math.cos(ta) * r1, cy + Math.sin(ta) * r1);
                ctx.stroke();
            }

            // ── 4. ПОЛОСЫ ЗВУКА. Наружу — что слышит, внутрь — что
            //    говорит: одно приходит извне, другое уходит.
            var bo = root.bandsOut, bi = root.bandsInn;
            var n = Math.min(bo.length, 96);
            if (n > 0) {
                var NB = n * 2;
                var step = Math.max(1, Math.round(NB / Math.max(8, 2 * Math.PI * R / 4.2)));
                var blw = Math.max(1.1, u * 0.0045 * Math.min(2.6, step));
                ctx.lineCap = "round";
                for (var b = 0; b < NB; b += step) {
                    var k = b < n ? b : NB - 1 - b;
                    var ang = (b / NB) * Math.PI * 2 - Math.PI / 2;
                    var cs = Math.cos(ang), sn = Math.sin(ang);
                    var ov = bo[k] || 0, iv = (bi && bi[k]) || 0;
                    if (ov > 0.02) {
                        var l1 = 2 + ov * L;
                        var g = ctx.createLinearGradient(
                            cx + cs * (R + 2), cy + sn * (R + 2),
                            cx + cs * (R + 2 + l1), cy + sn * (R + 2 + l1));
                        g.addColorStop(0, "rgba(255,255,255," + ((0.12 + ov * 0.26) * dim) + ")");
                        g.addColorStop(1, "rgba(255,255,255," + ((0.46 + ov * 0.42) * dim) + ")");
                        ctx.strokeStyle = g; ctx.lineWidth = blw;
                        ctx.beginPath();
                        ctx.moveTo(cx + cs * (R + 2), cy + sn * (R + 2));
                        ctx.lineTo(cx + cs * (R + 2 + l1), cy + sn * (R + 2 + l1));
                        ctx.stroke();
                    }
                    if (iv > 0.02) {
                        var l2 = 2 + iv * L * 0.72;
                        var g2 = ctx.createLinearGradient(
                            cx + cs * (R - 3), cy + sn * (R - 3),
                            cx + cs * (R - 3 - l2), cy + sn * (R - 3 - l2));
                        g2.addColorStop(0, "rgba(255,255,255," + ((0.40 + iv * 0.4) * dim) + ")");
                        g2.addColorStop(1, "rgba(255,255,255," + ((0.10 + iv * 0.2) * dim) + ")");
                        ctx.strokeStyle = g2; ctx.lineWidth = blw;
                        ctx.beginPath();
                        ctx.moveTo(cx + cs * (R - 3), cy + sn * (R - 3));
                        ctx.lineTo(cx + cs * (R - 3 - l2), cy + sn * (R - 3 - l2));
                        ctx.stroke();
                    }
                }
            }

            // ── 5. ШАР. Свет падает сверху — тот же источник, что даёт блик
            //    и тени в вырезанном имени.
            ctx.save();
            ctx.shadowColor = "rgba(0,0,0,0.85)";
            ctx.shadowBlur = u * 0.10;
            ctx.shadowOffsetY = u * 0.035;
            var sp = ctx.createRadialGradient(cx - rs * 0.34, cy - rs * 0.40, rs * 0.06,
                                              cx, cy, rs * 1.06);
            sp.addColorStop(0, "rgba(255,255,255,0.99)");
            sp.addColorStop(0.55, "rgba(228,231,238,0.94)");
            sp.addColorStop(1, "rgba(196,201,211,0.90)");
            ctx.fillStyle = sp;
            ctx.beginPath(); ctx.arc(cx, cy, rs, 0, Math.PI * 2); ctx.fill();
            ctx.restore();

            // нижняя кромка: у настоящего шара низ подбирает отражённый свет
            var lip = ctx.createLinearGradient(cx, cy + rs * 0.2, cx, cy + rs);
            lip.addColorStop(0, "rgba(20,24,32,0)");
            lip.addColorStop(1, "rgba(20,24,32,0.22)");
            ctx.fillStyle = lip;
            ctx.beginPath(); ctx.arc(cx, cy, rs, 0, Math.PI * 2); ctx.fill();

            // ободок под курсором — единственная подсказка, что тут жмут
            if (root.hovered) {
                ctx.lineWidth = 1;
                ctx.strokeStyle = "rgba(255,255,255,0.55)";
                ctx.beginPath(); ctx.arc(cx, cy, rs + 1, 0, Math.PI * 2); ctx.stroke();
            }
        }
    }

    /* ИМЯ ВЫРЕЗАНО В ШАРЕ, а не написано на нём: у настоящей выемки верхняя
       кромка уходит в тень, нижняя ловит свет. Двумя слоями — светлым под
       тёмным; ось X нулевая, потому что свет в этой сцене падает сверху. */
    Item {
        anchors.centerIn: parent
        width: root.u * 0.34; height: root.u * 0.34
        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 1
            text: "ANAMORF"
            color: "#ffffff"; opacity: 0.85
            font.pixelSize: Math.max(5, root.u * 0.036)
            font.letterSpacing: Math.max(1, root.u * 0.0095)
            font.weight: Font.Light
        }
        Text {
            anchors.centerIn: parent
            text: "ANAMORF"
            color: "#0d1017"
            font.pixelSize: Math.max(5, root.u * 0.036)
            font.letterSpacing: Math.max(1, root.u * 0.0095)
            font.weight: Font.Light
        }
    }

    /* ── РУКА ──
       Тащить можно за что угодно; щелчок по самому шару возвращает большое
       окно. Разница между щелчком и перетаскиванием — пройденный путь, а
       не место: иначе за шар нельзя было бы взяться. */
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: root.hovered ? Qt.PointingHandCursor : Qt.SizeAllCursor
        property real px: 0
        property real py: 0
        property real moved: 0

        onPositionChanged: function (m) {
            var dx = m.x - width / 2, dy = m.y - height / 2;
            root.hovered = !pressed && Math.sqrt(dx * dx + dy * dy) < root.u * 0.19;
            if (!pressed) return;
            moved += Math.abs(m.x - px) + Math.abs(m.y - py);
            bridge.moveBy(m.x - px, m.y - py);
        }
        onPressed: function (m) {
            if (m.button === Qt.RightButton) { bridge.menu(); return; }
            px = m.x; py = m.y; moved = 0;
            root.held = true; root.hovered = false;
        }
        onReleased: function (m) {
            root.held = false;
            if (m.button === Qt.RightButton) return;
            var dx = m.x - width / 2, dy = m.y - height / 2;
            var onCore = Math.sqrt(dx * dx + dy * dy) < root.u * 0.19;
            if (moved < 5 && onCore) bridge.back();
            else bridge.dropped();
        }
        onExited: root.hovered = false
        onWheel: function (e) { bridge.zoom(e.angleDelta.y) }
    }
}
