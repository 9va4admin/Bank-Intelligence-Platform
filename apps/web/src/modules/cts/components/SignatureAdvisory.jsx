import { msg } from '../../../shared/messages'

/** The signature score is a similarity from an embedding model, not a forgery test: say so next to the number, so it is not read as "verified". */
export default function SignatureAdvisory({ isDark }) {
  return (
    <p role="note" className={`text-[10px] leading-snug mt-1.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
      {msg('UI_SIGNATURE_ADVISORY_REVIEWER')}
    </p>
  )
}
