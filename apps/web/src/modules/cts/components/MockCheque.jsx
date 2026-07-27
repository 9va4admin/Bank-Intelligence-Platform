/**
 * Realistic CTS-2010 cheque mock components.
 *
 * Two visual templates chosen automatically by drawee bank name:
 *   HDFCStyleFront — private banks (HDFC, ICICI, Axis, Kotak …)
 *     Black logo box · large loose date digits · wavy security pattern
 *   PSBStyleFront — PSBs and co-op banks (SBI, BoB, Saraswat, NKGSB …)
 *     Coloured bank name · individual date digit boxes · CTS-2010 left strip
 *
 * Both accept the same flat props after normalisation.
 * MockChequeFront accepts either { inst } (ValidationQueue format)
 * or { item } (SubmissionQueue format) and normalises internally.
 */

// ── HDFC / private-bank style ─────────────────────────────────────────────────

function HDFCStyleFront({ bank, branch, date, payee, amtFig, amtWrd, micr, account, chqNo }) {
  const dd   = (date.split('/')[0] || '').padStart(2, '0')
  const mm   = (date.split('/')[1] || '').padStart(2, '0')
  const yyyy = (date.split('/')[2] || '').padStart(4, '0')

  return (
    <div style={{ width: '100%', maxWidth: '580px', aspectRatio: '2.55/1', background: '#fff', border: '1px solid #888', borderRadius: '2px', position: 'relative', overflow: 'hidden', boxShadow: '0 4px 24px rgba(0,0,0,0.2)', userSelect: 'none' }}>

      {/* Left fine security lines */}
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '10px', background: 'repeating-linear-gradient(90deg,#ddd 0,#ddd .5px,#fff .5px,#fff 3.5px)', borderRight: '0.5px solid #ccc' }} />

      {/* Wavy security background — bottom left, like real HDFC */}
      <svg viewBox="0 0 320 120" preserveAspectRatio="none"
        style={{ position: 'absolute', bottom: '16px', left: '12px', width: '50%', height: '48%', opacity: 0.1, pointerEvents: 'none' }}>
        {[0,9,18,27,36,46,57,70,85,102].map((y, i) => (
          <path key={i}
            d={`M0,${y} C50,${y-16} 90,${y+16} 130,${y} C170,${y-16} 210,${y+16} 250,${y} C280,${y-10} 305,${y+6} 320,${y}`}
            fill="none" stroke="#111" strokeWidth={i < 2 ? 3 : i < 5 ? 2.2 : i < 8 ? 1.5 : 1} />
        ))}
        {[4,13,22,31,40,51,62,76,91].map((y, i) => (
          <path key={`s${i}`}
            d={`M0,${y} C40,${y+12} 85,${y-12} 130,${y} C175,${y+12} 215,${y-12} 260,${y} C290,${y+8} 310,${y-4} 320,${y}`}
            fill="none" stroke="#333" strokeWidth={0.7} />
        ))}
      </svg>

      {/* Main content */}
      <div style={{ marginLeft: '12px', height: '100%', display: 'flex', flexDirection: 'column', padding: '5px 10px 18px 8px', boxSizing: 'border-box', fontFamily: 'Arial,sans-serif' }}>

        {/* Header: logo + date */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '5px' }}>
          <div>
            {/* Black logo box */}
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', background: '#000', color: '#fff', padding: '3px 8px 3px 5px', marginBottom: '3px' }}>
              <svg width="13" height="13" viewBox="0 0 13 13" style={{ flexShrink: 0 }}>
                <rect width="13" height="13" fill="none" />
                <line x1="2" y1="6.5" x2="11" y2="6.5" stroke="#fff" strokeWidth="1.8" />
                <line x1="6.5" y1="2" x2="6.5" y2="11" stroke="#fff" strokeWidth="1.8" />
                <rect x="1" y="1" width="11" height="11" fill="none" stroke="#fff" strokeWidth="1.2" />
              </svg>
              <span style={{ fontSize: '10px', fontWeight: 900, letterSpacing: '1.5px', lineHeight: 1 }}>
                {bank.toUpperCase()}
              </span>
            </div>
            <div style={{ fontSize: '6.5px', color: '#222', lineHeight: 1.5 }}>{branch}</div>
            <div style={{ fontSize: '6.5px', color: '#222' }}>
              RTGS / NEFT IFSC : {bank.replace(/\s/g, '').slice(0, 4).toUpperCase()}0{micr.slice(0, 7)}
            </div>
          </div>

          {/* Date — large loose digits, no boxes (HDFC style) */}
          <div style={{ textAlign: 'right', minWidth: '150px' }}>
            <div style={{ fontSize: '5.5px', color: '#888', marginBottom: '2px' }}>Weekly Holiday on SUNDAY</div>
            <div style={{ fontFamily: 'monospace', fontSize: '20px', fontWeight: 700, letterSpacing: '4px', color: '#111', lineHeight: 1 }}>
              {dd} {mm} {yyyy}
            </div>
            <div style={{ fontSize: '6px', color: '#777', letterSpacing: '3px' }}>D D  M M  Y Y Y Y</div>
            <div style={{ fontSize: '5.5px', color: '#888', marginTop: '1px' }}>Valid for 3 months only</div>
          </div>
        </div>

        {/* Pay line */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '5px', borderBottom: '0.8px solid #222', paddingBottom: '2px', marginBottom: '2px' }}>
          <span style={{ fontSize: '8.5px', fontWeight: 'bold', minWidth: '22px', lineHeight: 1 }}>Pay</span>
          <span style={{ flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '14px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.1 }}>
            {payee}
          </span>
          <div style={{ textAlign: 'right', lineHeight: 1.3, flexShrink: 0 }}>
            <div style={{ fontSize: '8.5px', fontWeight: 'bold' }}>Or Bearer</div>
            <div style={{ fontSize: '7px', color: '#333' }}>या धारक को</div>
          </div>
        </div>

        {/* Rupees line */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px', borderBottom: '0.8px solid #222', paddingBottom: '2px', marginBottom: '0' }}>
          <span style={{ fontSize: '8px', fontWeight: 'bold', whiteSpace: 'nowrap' }}>Rupees रुपये</span>
          <span style={{ flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {amtWrd}
          </span>
        </div>

        {/* Second underline + amount box */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', borderBottom: '0.8px solid #222', paddingBottom: '2px', marginBottom: '3px', gap: '6px' }}>
          <span style={{ fontSize: '7px', color: '#111' }}>अदा करें</span>
          <div style={{ display: 'flex', border: '1.5px solid #333', height: '25px', minWidth: '118px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 5px', borderRight: '1px solid #555', background: '#f8f8f4', minWidth: '22px' }}>
              <span style={{ fontSize: '14px', fontWeight: 'bold' }}>₹</span>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 6px' }}>
              <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', fontWeight: 700, whiteSpace: 'nowrap' }}>
                {amtFig}/-
              </span>
            </div>
          </div>
        </div>

        {/* Account section */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
          <div style={{ display: 'flex', border: '1px solid #666', borderRadius: '1px' }}>
            <div style={{ padding: '2px 5px', borderRight: '1px solid #999', background: '#f4f4ef', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '1px' }}>
              <div style={{ fontSize: '5.5px', color: '#555', lineHeight: 1 }}>A/c No.</div>
              <div style={{ fontSize: '5.5px', color: '#555', lineHeight: 1 }}>खाता सं.</div>
            </div>
            <div style={{ padding: '3px 10px', display: 'flex', alignItems: 'center' }}>
              <span style={{ fontFamily: 'monospace', fontSize: '11px', fontWeight: 'bold', letterSpacing: '0.5px' }}>
                {account.replace(/[●*]/g, '0').padStart(14, '0')}
              </span>
            </div>
          </div>
          <div style={{ fontSize: '6px', color: '#555', lineHeight: 1.5 }}>
            <div>Brn: {micr.slice(0, 4)}  Pdt: 100</div>
            <div>SB A/C</div>
          </div>
        </div>

        {/* Payable at par */}
        <div style={{ fontSize: '5.8px', color: '#666', marginBottom: '2px' }}>
          Payable at par through clearing/transfer at all branches of {bank.toUpperCase()} LTD
        </div>

        {/* Signature area */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end', alignItems: 'flex-end' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ width: '100px', borderTop: '1px solid #111', marginBottom: '1px' }} />
            <div style={{ fontSize: '7.5px', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{payee}</div>
            <div style={{ fontSize: '5.8px', color: '#555' }}>Please sign above / कृपया ऊपर हस्ताक्षर करें</div>
          </div>
        </div>
      </div>

      {/* MICR */}
      <div style={{ position: 'absolute', bottom: '1px', left: '12px', right: '8px', textAlign: 'center', fontFamily: 'monospace', fontSize: '8px', color: '#111', letterSpacing: '2px' }}>
        ‟{chqNo}‟  {micr}:  {account.replace(/[●*]/g, '0').padStart(12, '0').slice(0, 12)}‟  31
      </div>
    </div>
  )
}

// ── PSB / co-op bank style (NKGSB, SBI, Saraswat …) ─────────────────────────

function PSBStyleFront({ bank, branch, date, payee, amtFig, amtWrd, micr, account, chqNo }) {
  const parts   = date.split('/')
  const dd      = (parts[0] || '').padStart(2, ' ')
  const mm      = (parts[1] || '').padStart(2, ' ')
  const yyyy    = (parts[2] || '').padStart(4, ' ')
  const dDigits = [...dd, ...mm, ...yyyy]

  return (
    <div style={{ width: '100%', maxWidth: '580px', aspectRatio: '2.55/1', background: '#fefefe', border: '1px solid #999', borderRadius: '2px', position: 'relative', overflow: 'hidden', boxShadow: '0 4px 24px rgba(0,0,0,0.2)', userSelect: 'none' }}>

      {/* Left CTS-2010 security strip */}
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '14px', background: '#efefef', borderRight: '0.5px solid #ccc', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', fontSize: '4.5px', color: '#bbb', letterSpacing: '0.5px', fontFamily: 'Arial,sans-serif', whiteSpace: 'nowrap' }}>
          National Technologies Limited • Navi Mumbai / CTS-2010
        </span>
      </div>

      {/* Main content */}
      <div style={{ marginLeft: '16px', height: '100%', display: 'flex', flexDirection: 'column', padding: '5px 10px 18px 6px', boxSizing: 'border-box', fontFamily: 'Arial,sans-serif' }}>

        {/* Header: bank name + date boxes */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '3px' }}>
          <div>
            <div style={{ fontWeight: 900, fontSize: '12px', color: '#1a3a6e' }}>{bank}</div>
            <div style={{ fontSize: '6.5px', color: '#333', marginTop: '1px', lineHeight: 1.5 }}>{branch}</div>
            <div style={{ fontSize: '6.5px', color: '#555' }}>
              IFSC CODE : {bank.replace(/[^A-Za-z0-9]/g, '').slice(0, 4).toUpperCase()}0{micr.slice(0, 6)}
            </div>
          </div>

          {/* Individual date digit boxes (NKGSB style) */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '5.5px', color: '#777', marginBottom: '2px' }}>VALID FOR THREE MONTHS FROM DATE OF ISSUE</div>
            <div style={{ display: 'flex', gap: '1.5px', justifyContent: 'flex-end', alignItems: 'center' }}>
              <span style={{ fontSize: '7px', color: '#444', marginRight: '3px', lineHeight: 1.3 }}>दिनांक<br />Date</span>
              {dDigits.map((d, i) => (
                <span key={i} style={{
                  display: 'inline-flex', width: '14px', height: '17px',
                  border: '1px solid #555', justifyContent: 'center', alignItems: 'center',
                  fontFamily: 'monospace', fontWeight: 'bold', fontSize: '11px', background: '#fff',
                  marginLeft: (i === 2 || i === 4) ? '3px' : '0',
                }}>
                  {d?.trim() || ''}
                </span>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '1.5px', justifyContent: 'flex-end', marginTop: '1px', paddingLeft: '28px' }}>
              <span style={{ fontSize: '5px', color: '#999', width: '30px', textAlign: 'center' }}>D D</span>
              <span style={{ fontSize: '5px', color: '#999', width: '30px', textAlign: 'center', marginLeft: '3px' }}>M M</span>
              <span style={{ fontSize: '5px', color: '#999', width: '58px', textAlign: 'center', marginLeft: '3px' }}>Y Y Y Y</span>
            </div>
          </div>
        </div>

        {/* Pay line */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '5px', borderBottom: '0.8px solid #111', paddingBottom: '2px', marginBottom: '2px' }}>
          <span style={{ fontSize: '8.5px', fontWeight: 'bold', minWidth: '22px' }}>Pay</span>
          <span style={{ flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '14px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {payee}
          </span>
          <span style={{ fontSize: '7.5px', color: '#111', whiteSpace: 'nowrap', flexShrink: 0 }}>या धारक को Or Bearer</span>
        </div>

        {/* Rupees line + inline amount box */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '5px', marginBottom: '3px' }}>
          <div style={{ flex: 1, borderBottom: '0.8px solid #111', paddingBottom: '2px', display: 'flex', alignItems: 'baseline', gap: '4px' }}>
            <span style={{ fontSize: '8px', fontWeight: 'bold', whiteSpace: 'nowrap' }}>रुपये Rupees</span>
            <span style={{ flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {amtWrd}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
            <span style={{ fontSize: '7px', color: '#111', whiteSpace: 'nowrap' }}>अदा करें।</span>
            <div style={{ display: 'flex', border: '1.5px solid #333', height: '26px', minWidth: '110px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 5px', borderRight: '1px solid #555', background: '#f8f8f4', minWidth: '20px' }}>
                <span style={{ fontSize: '14px', fontWeight: 'bold' }}>₹</span>
              </div>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 5px' }}>
                <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {amtFig}/-
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Account box */}
        <div style={{ display: 'inline-flex', border: '1px solid #888', marginBottom: '3px' }}>
          <div style={{ padding: '2px 5px', borderRight: '1px solid #999', background: '#f4f4ef', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <span style={{ fontSize: '5.5px', color: '#555', lineHeight: 1.3 }}>खाता सं.</span>
            <span style={{ fontSize: '5.5px', color: '#555', lineHeight: 1.3 }}>A/c No.</span>
          </div>
          <div style={{ padding: '3px 10px', display: 'flex', alignItems: 'center' }}>
            <span style={{ fontFamily: 'monospace', fontSize: '11px', fontWeight: 'bold', letterSpacing: '0.5px' }}>
              {account.replace(/[●*]/g, '0').padStart(14, '0')}
            </span>
          </div>
        </div>

        {/* Footer: payable + signature */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: '6px', color: '#777' }}>Payable at par at all branches</div>
            <div style={{ fontSize: '7px', fontFamily: 'monospace', color: '#555' }}>{micr.slice(0, 6)}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ width: '100px', borderTop: '1px solid #111', marginBottom: '1px' }} />
            <div style={{ fontSize: '7.5px', fontWeight: 'bold', textTransform: 'uppercase' }}>{payee}</div>
            <div style={{ fontSize: '6px', color: '#555' }}>Please sign above</div>
          </div>
        </div>
      </div>

      {/* MICR */}
      <div style={{ position: 'absolute', bottom: '1px', left: '16px', right: '8px', textAlign: 'center', fontFamily: 'monospace', fontSize: '8px', color: '#111', letterSpacing: '2px' }}>
        ‟{chqNo}‟  {micr}:  {account.replace(/[●*]/g, '0').padStart(12, '0').slice(0, 12)}‟  31
      </div>
    </div>
  )
}

// ── Exported components ───────────────────────────────────────────────────────

export function MockChequeFront({ inst, item }) {
  let bank, branch, date, payee, amtFig, amtWrd, micr, account, chqNo

  if (inst) {
    const fm = inst.fields_meta || {}
    bank    = inst.drawee_bank
    branch  = inst.drawee_branch
    date    = fm.date?.actual_value            || ''
    payee   = fm.payee?.actual_value           || '—'
    amtFig  = (fm.amount_figures?.actual_value || '').replace('₹', '').trim()
    amtWrd  = fm.amount_words?.actual_value    || '—'
    micr    = fm.micr?.actual_value            || '000000000'
    account = inst.account_display             || '00000000000000'
    chqNo   = inst.instrument_id?.replace(/\D/g, '').slice(-6).padStart(6, '0') || '000001'
  } else if (item) {
    bank    = item.drawee_bank
    branch  = item.drawee_branch
    date    = item.date                        || ''
    payee   = item.payee                       || '—'
    amtFig  = (item.amount_figures || '').replace('₹', '').trim()
    amtWrd  = item.amount_words                || '—'
    micr    = item.micr                        || '000000000'
    account = item.account_display             || '00000000000000'
    chqNo   = item.instrument_id?.replace(/\D/g, '').slice(-6).padStart(6, '0') || '000001'
  }

  bank   = bank   || 'Bank'
  branch = branch || 'Main Branch'

  const isPrivate = /hdfc|icici|axis|kotak|yes\s*bank/i.test(bank)
  const props = { bank, branch, date, payee, amtFig, amtWrd, micr, account, chqNo }
  return isPrivate ? <HDFCStyleFront {...props} /> : <PSBStyleFront {...props} />
}

export function MockChequeBack() {
  return (
    <div style={{ width: '100%', maxWidth: '580px', aspectRatio: '2.55/1', background: '#f8f8f5', border: '1px solid #999', borderRadius: '2px', boxShadow: '0 4px 20px rgba(0,0,0,0.1)', fontFamily: 'Arial,sans-serif', position: 'relative', overflow: 'hidden' }}>
      <div style={{ padding: '14px 20px' }}>
        <div style={{ fontSize: '7px', color: '#aaa', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '1px' }}>Endorsement / पृष्ठांकन</div>
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
    bank    = inst.drawee_bank
    branch  = inst.drawee_branch
    date    = fm.date?.actual_value            || '—'
    payee   = fm.payee?.actual_value           || '—'
    amtFig  = fm.amount_figures?.actual_value  || '—'
    amtWrd  = fm.amount_words?.actual_value    || '—'
    account = inst.account_display             || '—'
  } else if (item) {
    bank    = item.drawee_bank
    branch  = item.drawee_branch
    date    = item.date            || '—'
    payee   = item.payee           || '—'
    amtFig  = item.amount_figures  || '—'
    amtWrd  = item.amount_words    || '—'
    account = item.account_display || '—'
  }
  bank = bank || 'Bank'; branch = branch || 'Branch'

  return (
    <div style={{ width: '100%', maxWidth: '380px', aspectRatio: '1.6/1', background: '#fff', border: '1.5px solid #3a6eaf', borderRadius: '2px', boxShadow: '0 4px 20px rgba(0,0,0,0.12)', overflow: 'hidden', fontFamily: 'Arial,sans-serif' }}>
      <div style={{ background: '#1a5faf', color: '#fff', padding: '5px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '9px', fontWeight: 'bold', letterSpacing: '0.5px' }}>PAY-IN SLIP / जमा पर्ची</div>
          <div style={{ fontSize: '6px', marginTop: '1px' }}>{bank} — {branch} Branch</div>
        </div>
        <div style={{ fontSize: '6.5px', textAlign: 'right' }}>
          <div>Date: {date}</div>
          <div style={{ marginTop: '1px' }}>Teller No.: 04</div>
        </div>
      </div>
      <div style={{ padding: '6px 12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px' }}>
        {[
          ['Account Name / खाता नाम', payee],
          ['Amount / राशि',           amtFig],
          ['Words / शब्दों में',       amtWrd],
          ['Account No. / खाता सं.',  account],
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
