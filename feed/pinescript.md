//@version=6
indicator("Kaya", shorttitle="Rakaindikator", overlay=true, max_bars_back=500)

// ============================================================
// HULL SUITE BY INSILICO — Length 160 & 80
// ============================================================

src        = input.source(close, "Source", group="Hull Suite")
modeSwitch = input.string("Hma", "Hull Variation", options=["Hma", "Thma", "Ehma"], group="Hull Suite")
length160  = input.int(160, "Length 160", minval=1, group="Hull Suite")
length80   = input.int(80,  "Length 80",  minval=1, group="Hull Suite")

HMA(_src, _length) =>
    ta.wma(2 * ta.wma(_src, _length / 2) - ta.wma(_src, _length), math.round(math.sqrt(_length)))

EHMA(_src, _length) =>
    ta.ema(2 * ta.ema(_src, _length / 2) - ta.ema(_src, _length), math.round(math.sqrt(_length)))

THMA(_src, _length) =>
    ta.wma(ta.wma(_src, _length / 3) * 3 - ta.wma(_src, _length / 2) - ta.wma(_src, _length), _length)

Mode(_mode, _src, _length) =>
    if _mode == "Ehma"
        EHMA(_src, _length)
    else if _mode == "Thma"
        THMA(_src, _length / 2)
    else
        HMA(_src, _length)

// Hull 160
HULL160      = Mode(modeSwitch, src, length160)
MHULL160     = HULL160[0]
SHULL160     = HULL160[2]
hullColor160 = MHULL160 > SHULL160 ? color.new(#00ff00, 0) : color.new(#ff0000, 0)

// Hull 80
HULL80      = Mode(modeSwitch, src, length80)
MHULL80     = HULL80[0]
SHULL80     = HULL80[2]
hullColor80 = MHULL80 > SHULL80 ? color.new(#00e5ff, 0) : color.new(#ff6d00, 0)

plot(MHULL160, title="Hull 160", color=hullColor160, linewidth=3)
plot(MHULL80,  title="Hull 80",  color=hullColor80,  linewidth=2)

// ============================================================
// SUPERTREND — ATR Length 2, Factor 3.3
// ============================================================

atrLength = input.int(2,    "ATR Length", minval=1,    group="Supertrend")
factor    = input.float(3.3, "Factor",    minval=0.01, step=0.01, group="Supertrend")

[supertrend, direction] = ta.supertrend(factor, atrLength)
supertrend := barstate.isfirst ? na : supertrend

bodyMiddle = plot(barstate.isfirst ? na : (open + close) / 2, "Body Middle", display=display.none)
upTrend    = plot(direction < 0 ? supertrend : na, "Up Trend",   color=color.green, style=plot.style_linebr, linewidth=2)
downTrend  = plot(direction < 0 ? na : supertrend, "Down Trend", color=color.red,   style=plot.style_linebr, linewidth=2)

// Background fill tipis ikut badan candle
fill(bodyMiddle, upTrend,   title="Uptrend Background",   color=color.new(color.green, 97), fillgaps=false)
fill(bodyMiddle, downTrend, title="Downtrend Background", color=color.new(color.red,   97), fillgaps=false)

// ============================================================
// SINYAL BUY / SELL — Mengikuti Supertrend
// ============================================================

showSignals = input.bool(true, "Tampilkan Sinyal BUY/SELL", group="Signals")

bullTrigger = direction[1] > direction  // Downtrend → Uptrend
bearTrigger = direction[1] < direction  // Uptrend → Downtrend

plotshape(showSignals and bullTrigger, title="BUY Signal",  location=location.belowbar, color=color.new(color.green, 0), style=shape.labelup,   text="BUY",  textcolor=color.black, size=size.small)
plotshape(showSignals and bearTrigger, title="SELL Signal", location=location.abovebar, color=color.new(color.red,   0), style=shape.labeldown, text="SELL", textcolor=color.white, size=size.small)

// ============================================================
// ALERT CONDITIONS
// ============================================================

alertcondition(direction[1] > direction,  title="Downtrend to Uptrend (BUY)",  message="Hull+Supertrend: Sinyal BUY — Trend berubah dari Downtrend ke Uptrend")
alertcondition(direction[1] < direction,  title="Uptrend to Downtrend (SELL)", message="Hull+Supertrend: Sinyal SELL — Trend berubah dari Uptrend ke Downtrend")
alertcondition(direction[1] != direction, title="Trend Change",                 message="Hull+Supertrend: Trend berubah arah")