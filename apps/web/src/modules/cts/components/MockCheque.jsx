/**
 * Realistic CTS-2010 cheque mock components.
 *
 * Two visual templates chosen automatically by drawee bank name:
 *   HDFCStyleFront — private banks (HDFC, ICICI, Axis, Kotak …)
 *   PSBStyleFront  — PSBs and co-op banks (SBI, BoB, Saraswat, NKGSB …)
 *
 * Signature area layout (bottom-right corner):
 *   [cursive handwriting — above the line]
 *   ─────────────────── (sig line)
 *   DRAWER NAME  (bank pre-printed block letters)
 *   Please sign above / कृपया ऊपर हस्ताक्षर करें
 *
 * MICR band: fixed-height strip at very bottom, never overlaps cheque body.
 */

// ── Helpers ───────────────────────────────────────────────────────────────────

const MON_MAP = { Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',
                  Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12' }

function parseDMY(date) {
  if (!date) return { dd:'15', mm:'07', yyyy:'2026' }
  const sep = date.includes('/') ? '/' : '-'
  const p   = date.split(sep)
  return {
    dd:   (p[0] || '15').padStart(2, '0'),
    mm:   MON_MAP[p[1]] || (p[1] || '07').padStart(2, '0'),
    yyyy: (p[2] || '2026').padStart(4, '0'),
  }
}

/**
 * Realistic cursive signature SVG.
 * seed (0-2) picks one of three distinct styles so different drawers look different.
 */
function SignatureSquiggle({ width = 100, seed = 0 }) {
  const w = width
  const h = 28

  const sigs = [
    // Style 0 — flowing loops with underline flourish
    <>
      <path
        d={`M${w*.04},${h*.68} C${w*.1},${h*.22} ${w*.18},${h*.88} ${w*.26},${h*.52}
            C${w*.3},${h*.36} ${w*.36},${h*.76} ${w*.42},${h*.52}
            C${w*.48},${h*.28} ${w*.54},${h*.68} ${w*.6},${h*.46}
            C${w*.65},${h*.28} ${w*.72},${h*.62} ${w*.8},${h*.42}
            C${w*.86},${h*.26} ${w*.92},${h*.5} ${w*.97},${h*.4}`}
        stroke="#1a1a1a" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d={`M${w*.08},${h*.82} C${w*.3},${h*.74} ${w*.62},${h*.8} ${w*.86},${h*.7}`}
        stroke="#1a1a1a" strokeWidth="1.0" fill="none" strokeLinecap="round"
      />
    </>,
    // Style 1 — angular, businesslike
    <>
      <path
        d={`M${w*.03},${h*.58} L${w*.12},${h*.18} L${w*.2},${h*.66}
            C${w*.25},${h*.82} ${w*.32},${h*.32} ${w*.4},${h*.54}
            L${w*.5},${h*.18} C${w*.56},${h*.04} ${w*.63},${h*.36} ${w*.68},${h*.5}
            C${w*.74},${h*.64} ${w*.82},${h*.34} ${w*.93},${h*.44}`}
        stroke="#1a1a1a" strokeWidth="1.3" fill="none" strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d={`M${w*.12},${h*.74} C${w*.36},${h*.64} ${w*.66},${h*.7} ${w*.9},${h*.6}`}
        stroke="#1a1a1a" strokeWidth="0.9" fill="none" strokeLinecap="round"
      />
    </>,
    // Style 2 — compact loops with accent strokes
    <>
      <path
        d={`M${w*.04},${h*.5} C${w*.08},${h*.18} ${w*.15},${h*.78} ${w*.23},${h*.44}
            C${w*.29},${h*.2} ${w*.35},${h*.72} ${w*.43},${h*.5}
            C${w*.5},${h*.28} ${w*.56},${h*.7} ${w*.64},${h*.48}
            C${w*.7},${h*.28} ${w*.77},${h*.62} ${w*.85},${h*.42}
            C${w*.9},${h*.26} ${w*.96},${h*.5} ${w*.99},${h*.36}`}
        stroke="#1a1a1a" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d={`M${w*.23},${h*.62} C${w*.27},${h*.52} ${w*.31},${h*.66} ${w*.35},${h*.58}`}
        stroke="#1a1a1a" strokeWidth="0.9" fill="none" strokeLinecap="round"
      />
      <path
        d={`M${w*.64},${h*.6} C${w*.68},${h*.5} ${w*.73},${h*.65} ${w*.77},${h*.56}`}
        stroke="#1a1a1a" strokeWidth="0.9" fill="none" strokeLinecap="round"
      />
    </>,
  ]

  return (
    <svg width={width} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      {sigs[seed % 3]}
    </svg>
  )
}

/**
 * Signature block — shared between HDFC and PSB templates.
 * Order: cursive sig → line → drawer name → "Please sign above"
 */
function SigBlock({ drawerName, seed = 0 }) {
  return (
    <div style={{ textAlign: 'right', paddingBottom: '2px' }}>
      {/* Cursive handwriting above the line */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <SignatureSquiggle width={96} seed={seed} />
      </div>
      {/* Signature line */}
      <div style={{ borderTop: '0.8px solid #222', marginBottom: '2px' }} />
      {/* Bank pre-printed drawer name (always different from payee) */}
      {drawerName && (
        <div style={{
          fontSize: '6.5px', fontWeight: 900, textTransform: 'uppercase',
          color: '#555', letterSpacing: '0.5px', marginBottom: '2px',
        }}>
          {drawerName}
        </div>
      )}
      <div style={{ fontSize: '5.5px', color: '#777', whiteSpace: 'nowrap' }}>
        Please sign above / {'कृपया ऊपर हस्ताक्षर करें'}
      </div>
    </div>
  )
}

// ── HDFC / private-bank style ─────────────────────────────────────────────────

function HDFCStyleFront({ bank, branch, date, payee, amtFig, amtWrd, micr, account, chqNo, drawerName }) {
  const { dd, mm, yyyy } = parseDMY(date)
  const acctDisp = account.replace(/[●*]/g, '0').padStart(14, '0')
  const micrLine = `‟${chqNo}‟  ${micr}:  ${acctDisp.slice(-12)}‟  31`
  const sigSeed  = (drawerName || payee).charCodeAt(0) % 3

  return (
    <div style={{
      width: '100%', maxWidth: '580px', aspectRatio: '2.55/1',
      display: 'flex', flexDirection: 'column',
      background: '#fff', border: '1px solid #888', borderRadius: '2px',
      position: 'relative', overflow: 'hidden',
      boxShadow: '0 4px 24px rgba(0,0,0,0.22)', userSelect: 'none',
    }}>

      {/* Left thin security-line strip */}
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: '10px',
        background: 'repeating-linear-gradient(90deg,#ccc 0,#ccc .5px,#fff .5px,#fff 3.5px)',
        borderRight: '0.5px solid #ccc',
      }} />

      {/* Wavy guilloche background */}
      <svg viewBox="0 0 280 100" preserveAspectRatio="none" style={{
        position: 'absolute', bottom: '20px', left: '14px',
        width: '46%', height: '43%', opacity: 0.08, pointerEvents: 'none',
      }}>
        {[5,14,23,32,41,50,59,68,77,86,95].map((y, i) => (
          <path key={i} fill="none" stroke="#000"
            strokeWidth={i < 3 ? 2.8 : i < 6 ? 1.8 : 1.2}
            d={`M0,${y} C50,${y-14} 90,${y+14} 140,${y} C190,${y-14} 235,${y+14} 280,${y}`}
          />
        ))}
        {[10,19,28,37,46,55,64,73,82,91].map((y, i) => (
          <path key={`s${i}`} fill="none" stroke="#444" strokeWidth={0.6}
            d={`M0,${y} C40,${y+11} 90,${y-11} 140,${y} C190,${y+11} 240,${y-11} 280,${y}`}
          />
        ))}
      </svg>

      {/* ── Cheque body ── */}
      <div style={{
        flex: 1, marginLeft: '12px', display: 'flex', flexDirection: 'column',
        padding: '5px 10px 3px 8px', boxSizing: 'border-box', fontFamily: 'Arial,sans-serif',
        position: 'relative', minHeight: 0,
      }}>

        {/* Row 1 — Logo left / Date right */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
          <div>
            <div style={{
              display: 'inline-block', border: '1px solid #555',
              padding: '1px 5px', fontSize: '5px', fontWeight: 900,
              letterSpacing: '0.6px', color: '#444', marginBottom: '4px',
            }}>A/C PAYEE ONLY</div>
            <div style={{
              display: 'flex', alignItems: 'center', gap: '5px',
              background: '#000', color: '#fff', padding: '3px 8px 3px 5px', marginBottom: '3px',
            }}>
              <svg width="12" height="12" viewBox="0 0 12 12">
                <rect width="12" height="12" fill="none"/>
                <line x1="2" y1="6" x2="10" y2="6" stroke="#fff" strokeWidth="1.8"/>
                <line x1="6" y1="2" x2="6" y2="10" stroke="#fff" strokeWidth="1.8"/>
                <rect x="1" y="1" width="10" height="10" fill="none" stroke="#fff" strokeWidth="1"/>
              </svg>
              <span style={{ fontSize: '10px', fontWeight: 900, letterSpacing: '1.5px', lineHeight: 1 }}>
                {bank.toUpperCase()}
              </span>
            </div>
            <div style={{ fontSize: '6.5px', color: '#222', lineHeight: 1.5 }}>{branch}</div>
            <div style={{ fontSize: '6px', color: '#333' }}>
              RTGS/NEFT IFSC : {bank.replace(/\s/g,'').slice(0,4).toUpperCase()}0{micr.slice(0,7)}
            </div>
          </div>

          {/* Date — large loose digits */}
          <div style={{ textAlign: 'right', minWidth: '160px' }}>
            <div style={{ fontSize: '5.5px', color: '#999', marginBottom: '3px' }}>Weekly Holiday on SUNDAY</div>
            <div style={{
              fontFamily: "'Courier New',monospace", fontSize: '23px', fontWeight: 700,
              letterSpacing: '5px', color: '#111', lineHeight: 1,
            }}>
              {dd} {mm} {yyyy}
            </div>
            <div style={{ fontSize: '6px', color: '#888', letterSpacing: '4px', marginTop: '2px' }}>
              D D&nbsp;&nbsp;M M&nbsp;&nbsp;Y Y Y Y
            </div>
            <div style={{ fontSize: '5.5px', color: '#aaa', marginTop: '2px' }}>Valid for 3 months only</div>
          </div>
        </div>

        {/* Row 2 — Pay line */}
        <div style={{
          display: 'flex', alignItems: 'flex-end', gap: '6px',
          borderBottom: '0.8px solid #111', paddingBottom: '2px', marginBottom: '2px',
        }}>
          <span style={{ fontSize: '9px', fontWeight: 900, minWidth: '24px', whiteSpace: 'nowrap', lineHeight: 1 }}>Pay</span>
          <span style={{
            flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontWeight: 700,
            fontSize: '14px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            lineHeight: 1.1, textDecoration: 'underline',
          }}>{payee}</span>
          <div style={{ textAlign: 'right', lineHeight: 1.3, flexShrink: 0 }}>
            <div style={{ fontSize: '8.5px', fontWeight: 'bold' }}>Or Bearer</div>
            <div style={{ fontSize: '7px', color: '#444' }}>{'या धारक को'}</div>
          </div>
        </div>

        {/* Row 3 — Rupees words + amount box */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '6px', marginBottom: '2px' }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'flex-end', gap: '5px',
            borderBottom: '0.8px solid #111', paddingBottom: '2px',
          }}>
            <span style={{ fontSize: '8px', fontWeight: 900, whiteSpace: 'nowrap', lineHeight: 1 }}>Rupees {'रुपये'}</span>
            <span style={{
              flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.1,
            }}>{amtWrd}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0, paddingBottom: '2px' }}>
            <span style={{ fontSize: '6.5px', color: '#222', whiteSpace: 'nowrap' }}>{'अदा करें'}</span>
            <div style={{ display: 'flex', border: '1.5px solid #333', height: '24px', minWidth: '112px' }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: '0 5px', borderRight: '1px solid #555', background: '#f5f5ee', minWidth: '20px',
              }}>
                <span style={{ fontSize: '14px', fontWeight: 900 }}>&#8377;</span>
              </div>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 6px' }}>
                <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {amtFig}/-
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Row 4 — Account box */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
          <div style={{ display: 'flex', border: '1px solid #777', borderRadius: '1px' }}>
            <div style={{
              padding: '2px 5px', borderRight: '1px solid #aaa',
              background: '#f5f5ee', display: 'flex', flexDirection: 'column', justifyContent: 'center',
            }}>
              <div style={{ fontSize: '5.5px', color: '#555', lineHeight: 1.3 }}>A/c No.</div>
              <div style={{ fontSize: '5.5px', color: '#555', lineHeight: 1.3 }}>{'खाता सं.'}</div>
            </div>
            <div style={{ padding: '3px 10px', display: 'flex', alignItems: 'center' }}>
              <span style={{ fontFamily: "'Courier New',monospace", fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.5px' }}>
                {acctDisp}
              </span>
            </div>
          </div>
          <div style={{ fontSize: '6px', color: '#666', lineHeight: 1.6 }}>
            <div>Brn: {micr.slice(0,4)}&nbsp;&nbsp;Pdt: 100</div>
            <div>SB A/C</div>
          </div>
        </div>

        {/* Row 5 — Payable at par + Signature */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div style={{ fontSize: '5.8px', color: '#777', maxWidth: '54%', lineHeight: 1.5 }}>
            Payable at par through clearing / transfer at all branches of {bank.toUpperCase()}
          </div>
          <SigBlock drawerName={drawerName} seed={sigSeed} />
        </div>
      </div>

      {/* ── MICR band ── */}
      <div style={{
        flexShrink: 0, height: '18px',
        background: '#f0ede0', borderTop: '0.5px solid #ccc', marginLeft: '12px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'Courier New',monospace", fontSize: '8px', color: '#111', letterSpacing: '2.5px',
      }}>
        {micrLine}
      </div>
    </div>
  )
}

// ── PSB / co-op bank style (SBI, BoB, Saraswat, NKGSB …) ────────────────────

function PSBStyleFront({ bank, branch, date, payee, amtFig, amtWrd, micr, account, chqNo, drawerName }) {
  const { dd, mm, yyyy } = parseDMY(date)
  const dDigits  = [...dd, ...mm, ...yyyy]
  const acctDisp = account.replace(/[●*]/g, '0').padStart(14, '0')
  const micrLine = `‟${chqNo}‟  ${micr}:  ${acctDisp.slice(-12)}‟  31`
  const sigSeed  = (drawerName || payee).charCodeAt(0) % 3

  return (
    <div style={{
      width: '100%', maxWidth: '580px', aspectRatio: '2.55/1',
      display: 'flex', flexDirection: 'column',
      background: '#fefefe', border: '1px solid #999', borderRadius: '2px',
      position: 'relative', overflow: 'hidden',
      boxShadow: '0 4px 24px rgba(0,0,0,0.2)', userSelect: 'none',
    }}>

      {/* Left CTS-2010 security strip */}
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: '14px',
        background: '#efefef', borderRight: '0.5px solid #ccc',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <span style={{
          writingMode: 'vertical-rl', transform: 'rotate(180deg)',
          fontSize: '4px', color: '#ccc', letterSpacing: '0.5px',
          fontFamily: 'Arial,sans-serif', whiteSpace: 'nowrap',
        }}>
          National Technologies Limited • Navi Mumbai / CTS-2010
        </span>
      </div>

      {/* ── Cheque body ── */}
      <div style={{
        flex: 1, marginLeft: '16px', display: 'flex', flexDirection: 'column',
        padding: '5px 10px 3px 6px', boxSizing: 'border-box', fontFamily: 'Arial,sans-serif',
        position: 'relative', minHeight: 0,
      }}>

        {/* Row 1 — Bank name left / Date boxes right */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '3px' }}>
          <div>
            <div style={{
              display: 'inline-block', border: '1px solid #555',
              padding: '1px 4px', fontSize: '5px', fontWeight: 900,
              letterSpacing: '0.5px', color: '#444', marginBottom: '3px',
            }}>A/C PAYEE ONLY</div>
            <div style={{ fontWeight: 900, fontSize: '12px', color: '#1a3a6e', lineHeight: 1 }}>{bank}</div>
            <div style={{ fontSize: '6.5px', color: '#333', marginTop: '2px', lineHeight: 1.5 }}>{branch}</div>
            <div style={{ fontSize: '6px', color: '#555' }}>
              IFSC : {bank.replace(/[^A-Za-z0-9]/g,'').slice(0,4).toUpperCase()}0{micr.slice(0,6)}
            </div>
          </div>

          {/* Individual bordered date digit boxes */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '5.5px', color: '#888', marginBottom: '3px' }}>
              VALID FOR THREE MONTHS FROM DATE OF ISSUE
            </div>
            <div style={{ display: 'flex', gap: '1.5px', justifyContent: 'flex-end', alignItems: 'center' }}>
              <span style={{ fontSize: '6.5px', color: '#555', marginRight: '3px', lineHeight: 1.3, textAlign: 'right' }}>
                {'दिनांक'}<br />Date
              </span>
              {dDigits.map((d, i) => (
                <div key={i} style={{
                  display: 'inline-flex', width: '14px', height: '18px',
                  border: '1px solid #555', justifyContent: 'center', alignItems: 'center',
                  background: '#fff', marginLeft: (i === 2 || i === 4) ? '3px' : '0',
                }}>
                  <span style={{ fontFamily: "'Courier New',monospace", fontWeight: 900, fontSize: '11px', lineHeight: 1 }}>
                    {d?.trim() || ''}
                  </span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '1.5px', justifyContent: 'flex-end', marginTop: '1px', paddingLeft: '28px' }}>
              <span style={{ fontSize: '5px', color: '#999', width: '30px', textAlign: 'center' }}>D D</span>
              <span style={{ fontSize: '5px', color: '#999', width: '30px', textAlign: 'center', marginLeft: '3px' }}>M M</span>
              <span style={{ fontSize: '5px', color: '#999', width: '58px', textAlign: 'center', marginLeft: '3px' }}>Y Y Y Y</span>
            </div>
          </div>
        </div>

        {/* Row 2 — Pay line */}
        <div style={{
          display: 'flex', alignItems: 'flex-end', gap: '5px',
          borderBottom: '0.8px solid #111', paddingBottom: '2px', marginBottom: '2px',
        }}>
          <span style={{ fontSize: '9px', fontWeight: 900, minWidth: '24px', lineHeight: 1 }}>Pay</span>
          <span style={{
            flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontWeight: 700,
            fontSize: '14px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            lineHeight: 1.1, textDecoration: 'underline',
          }}>{payee}</span>
          <span style={{ fontSize: '7.5px', color: '#111', whiteSpace: 'nowrap', flexShrink: 0 }}>
            {'या धारक को'} / Or Bearer
          </span>
        </div>

        {/* Row 3 — Rupees words + amount box */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '6px', marginBottom: '3px' }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'flex-end', gap: '4px',
            borderBottom: '0.8px solid #111', paddingBottom: '2px',
          }}>
            <span style={{ fontSize: '8px', fontWeight: 900, whiteSpace: 'nowrap', lineHeight: 1 }}>{'रुपये'} Rupees</span>
            <span style={{
              flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.1,
            }}>{amtWrd}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0, paddingBottom: '2px' }}>
            <span style={{ fontSize: '7px', color: '#111', whiteSpace: 'nowrap' }}>{'अदा करें।'}</span>
            <div style={{ display: 'flex', border: '1.5px solid #333', height: '24px', minWidth: '110px' }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: '0 5px', borderRight: '1px solid #555', background: '#f8f8f4', minWidth: '20px',
              }}>
                <span style={{ fontSize: '14px', fontWeight: 900 }}>&#8377;</span>
              </div>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 5px' }}>
                <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {amtFig}/-
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Row 4 — Account box */}
        <div style={{ display: 'inline-flex', border: '1px solid #888', marginBottom: '3px', alignSelf: 'flex-start' }}>
          <div style={{
            padding: '2px 5px', borderRight: '1px solid #999',
            background: '#f4f4ef', display: 'flex', flexDirection: 'column', justifyContent: 'center',
          }}>
            <span style={{ fontSize: '5.5px', color: '#555', lineHeight: 1.4 }}>{'खाता सं.'}</span>
            <span style={{ fontSize: '5.5px', color: '#555', lineHeight: 1.4 }}>A/c No.</span>
          </div>
          <div style={{ padding: '3px 10px', display: 'flex', alignItems: 'center' }}>
            <span style={{ fontFamily: "'Courier New',monospace", fontSize: '11px', fontWeight: 900, letterSpacing: '0.5px' }}>
              {acctDisp}
            </span>
          </div>
        </div>

        {/* Row 5 — Payable + Signature */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: '5.8px', color: '#777', lineHeight: 1.5 }}>
              Payable at par at all branches
            </div>
            <div style={{ fontSize: '7px', fontFamily: "'Courier New',monospace", color: '#555' }}>
              {micr.slice(0,6)}
            </div>
          </div>
          <SigBlock drawerName={drawerName} seed={sigSeed} />
        </div>
      </div>

      {/* ── MICR band ── */}
      <div style={{
        flexShrink: 0, height: '18px',
        background: '#f0ede0', borderTop: '0.5px solid #ccc', marginLeft: '16px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'Courier New',monospace", fontSize: '8px', color: '#111', letterSpacing: '2.5px',
      }}>
        {micrLine}
      </div>
    </div>
  )
}

// ── Exported components ───────────────────────────────────────────────────────

export function MockChequeFront({ inst, item }) {
  let bank, branch, date, payee, drawerName, amtFig, amtWrd, micr, account, chqNo

  if (inst) {
    const fm = inst.fields_meta || {}
    bank       = inst.drawee_bank
    branch     = inst.drawee_branch
    date       = fm.date?.actual_value            || ''
    payee      = fm.payee?.actual_value           || '—'
    drawerName = inst.drawer_name                 || ''
    amtFig     = (fm.amount_figures?.actual_value || '').replace('₹', '').trim()
    amtWrd     = fm.amount_words?.actual_value    || '—'
    micr       = fm.micr?.actual_value            || '000000000'
    account    = inst.account_display             || '00000000000000'
    chqNo      = inst.instrument_id?.replace(/\D/g, '').slice(-6).padStart(6, '0') || '000001'
  } else if (item) {
    bank       = item.drawee_bank
    branch     = item.drawee_branch
    date       = item.date                        || ''
    payee      = item.payee                       || '—'
    drawerName = item.drawer_name                 || ''
    amtFig     = (item.amount_figures || '').replace('₹', '').trim()
    amtWrd     = item.amount_words                || '—'
    micr       = item.micr                        || '000000000'
    account    = item.account_display             || '00000000000000'
    chqNo      = item.instrument_id?.replace(/\D/g, '').slice(-6).padStart(6, '0') || '000001'
  }

  bank   = bank   || 'Bank'
  branch = branch || 'Main Branch'

  const isPrivate = /hdfc|icici|axis|kotak|yes\s*bank/i.test(bank)
  const props = { bank, branch, date, payee, drawerName, amtFig, amtWrd, micr, account, chqNo }
  return isPrivate ? <HDFCStyleFront {...props} /> : <PSBStyleFront {...props} />
}

export function MockChequeBack({ depositChannel, item, inst }) {
  const payee     = item?.payee  || inst?.fields_meta?.payee?.actual_value  || ''
  const dd        = item?.deposit_data || inst?.deposit_data || {}
  const acctBA    = dd.extracted_account  || item?.account_display || '00000000000000'
  const mobileBA  = dd.extracted_mobile   || ''
  const acctKiosk = dd.account            || item?.account_display || '00000000000000'
  const nameKiosk = dd.name               || payee
  const txnKiosk  = dd.txn_id             || `CDM-${acctKiosk.slice(-4)}`

  return (
    <div style={{ width: '100%', maxWidth: '580px', aspectRatio: '2.55/1', background: '#f8f8f5', border: '1px solid #999', borderRadius: '2px', boxShadow: '0 4px 20px rgba(0,0,0,0.1)', fontFamily: 'Arial,sans-serif', position: 'relative', overflow: 'hidden' }}>
      <div style={{ padding: '14px 20px' }}>
        <div style={{ fontSize: '7px', color: '#aaa', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '1px' }}>Endorsement / {'पृष्ठांकन'}</div>

        {depositChannel === 'BACK_ANNOTATION' && (
          <div style={{ marginBottom: '8px', padding: '6px 8px', background: 'rgba(255,255,200,0.5)', border: '0.5px solid #bbb', borderRadius: '2px' }}>
            <div style={{ fontFamily: 'cursive', fontSize: '11px', color: '#222', lineHeight: 1.8 }}>
              A/c No: {acctBA}<br />
              {payee && <span>Name: {payee}<br /></span>}
              Mob: {mobileBA}
            </div>
          </div>
        )}

        {depositChannel === 'KIOSK' && (
          <div style={{ marginBottom: '8px', padding: '6px 10px', background: '#fff', border: '1px dashed #888', borderRadius: '2px', display: 'inline-block' }}>
            <div style={{ fontSize: '6px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '3px' }}>CDM DEPOSIT LABEL</div>
            <div style={{ fontFamily: 'monospace', fontSize: '9px', color: '#111', lineHeight: 1.7 }}>
              A/C: {acctKiosk}<br />
              {nameKiosk && <span>NAME: {nameKiosk.toUpperCase()}<br /></span>}
              TXN: {txnKiosk}
            </div>
            <div style={{ fontSize: '5.5px', color: '#aaa', marginTop: '3px' }}>Kiosk-captured · System-verified</div>
          </div>
        )}

        {[0, 1, 2].map(i => (
          <div key={i} style={{ borderBottom: '0.5px solid #ccc', marginBottom: i < 2 ? '22px' : 0 }} />
        ))}
        <div style={{ marginTop: '14px', fontSize: '7px', color: '#ddd' }}>For account payee only</div>
        <div style={{ marginTop: '6px', borderBottom: '0.5px solid #ccc', width: '130px' }} />
        <div style={{ fontSize: '6.5px', color: '#ddd', marginTop: '2px' }}>Authorised Signatory</div>
      </div>
      <div style={{ position: 'absolute', bottom: '8px', right: '16px', fontSize: '6.5px', color: '#ccc', fontFamily: 'monospace' }}>CTS-2010 Compliant</div>
    </div>
  )
}

export function MockPayinSlip({ inst, item }) {
  let bank, branch, date, payee, amtFig, amtWrd, account

  if (inst) {
    const fm = inst.fields_meta || {}
    const dd = inst.deposit_data || {}
    bank    = inst.drawee_bank
    branch  = inst.drawee_branch || dd.branch
    date    = fm.date?.actual_value           || dd.date  || '—'
    payee   = dd.depositor_name || fm.payee?.actual_value || '—'
    amtFig  = dd.deposit_amount || fm.amount_figures?.actual_value || '—'
    amtWrd  = fm.amount_words?.actual_value   || '—'
    account = dd.depositor_account || inst.account_display || '—'
  } else if (item) {
    const dd = item.deposit_data || {}
    bank    = item.drawee_bank
    branch  = item.drawee_branch || dd.branch
    date    = dd.date           || item.date           || '—'
    payee   = dd.depositor_name || item.payee          || '—'
    amtFig  = dd.deposit_amount || item.amount_figures || '—'
    amtWrd  = item.amount_words || '—'
    account = dd.depositor_account || item.account_display || '—'
  }
  bank = bank || 'Bank'; branch = branch || 'Branch'

  return (
    <div style={{ width: '100%', maxWidth: '380px', aspectRatio: '1.6/1', background: '#fff', border: '1.5px solid #3a6eaf', borderRadius: '2px', boxShadow: '0 4px 20px rgba(0,0,0,0.12)', overflow: 'hidden', fontFamily: 'Arial,sans-serif' }}>
      <div style={{ background: '#1a5faf', color: '#fff', padding: '5px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '9px', fontWeight: 'bold', letterSpacing: '0.5px' }}>PAY-IN SLIP / {'जमा पर्ची'}</div>
          <div style={{ fontSize: '6px', marginTop: '1px' }}>{bank} — {branch} Branch</div>
        </div>
        <div style={{ fontSize: '6.5px', textAlign: 'right' }}>
          <div>Date: {date}</div>
          <div style={{ marginTop: '1px' }}>Token: {(item?.deposit_data || inst?.deposit_data)?.counter_token || 'T-0001'}</div>
        </div>
      </div>
      <div style={{ padding: '6px 12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px' }}>
        {[
          ['Account Name / खाता नाम', payee],
          ['Amount / राशि',                           amtFig],
          ['शब्दों में / Words', amtWrd],
          ['Account No. / खाता सं.',        account],
        ].map(([label, val]) => (
          <div key={label}>
            <div style={{ fontSize: '5.5px', color: '#888', textTransform: 'uppercase' }}>{label}</div>
            <div style={{ fontSize: '8px', fontWeight: 'bold', color: '#111', borderBottom: '0.5px solid #ddd', paddingBottom: '1px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{ padding: '4px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontSize: '5.5px', color: '#aaa' }}>TELLER STAMP</div>
          <div style={{ width: '56px', height: '18px', border: '0.5px dashed #ddd', borderRadius: '2px' }} />
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ width: '80px', borderTop: '0.5px solid #555', marginBottom: '1px' }} />
          <div style={{ fontSize: '6px', color: '#888' }}>Depositor's Signature</div>
        </div>
      </div>
    </div>
  )
}
