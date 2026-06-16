/**
 * Shared dashboard design system — thin, consistent wrappers over HeroUI v2.
 *
 * Centralising field styling here means every form across the dashboard
 * looks identical. Labels render ABOVE the control (reliable in RTL —
 * HeroUI's labelPlacement="outside" overlaps its placeholder in Arabic).
 *
 * Exports:
 *   TextField   — text / password / number input
 *   TextArea    — multi-line textarea
 *   SelectField — styled <Select>
 *   Field       — bare label+error wrapper
 *   SectionCard — card container for settings sections
 *   SectionTitle — icon + title + description header block
 *   InlineAlert — inline success/error feedback message
 *   OptionCard  — selection card (tone / language / length pickers)
 *   SaveBtn     — consistent full-width primary save button
 *   FIELD_INPUT / FIELD_TEXTAREA — raw classNames if you need raw HeroUI
 */
import { Input, Textarea, Select, SelectItem, Button, Spinner } from '@heroui/react'
import type { ReactNode } from 'react'

// ── Tokens ────────────────────────────────────────────────────────────────────
export const FIELD_INPUT = {
  inputWrapper:
    'border-default-200 bg-default-50 h-12 min-h-12 rounded-xl px-4 ' +
    'data-[hover=true]:border-default-300 ' +
    'group-data-[focus=true]:!border-primary group-data-[focus=true]:!bg-content1 ' +
    'group-data-[focus=true]:ring-2 group-data-[focus=true]:ring-primary/15 ' +
    'transition-all duration-150',
  input: 'text-foreground text-sm placeholder:text-default-400',
}

export const FIELD_TEXTAREA = {
  inputWrapper:
    'border-default-200 bg-default-50 rounded-xl px-4 py-3 !h-auto items-start ' +
    'data-[hover=true]:border-default-300 ' +
    'group-data-[focus=true]:!border-primary group-data-[focus=true]:!bg-content1 ' +
    'group-data-[focus=true]:ring-2 group-data-[focus=true]:ring-primary/15 ' +
    'transition-all duration-150',
  input: 'text-foreground text-sm leading-relaxed placeholder:text-default-400 py-0.5',
}

// ── Field wrapper: label + optional hint + error ──────────────────────────────
export function Field({ label, hint, error, required, children }: {
  label?: string
  hint?: string
  error?: string
  required?: boolean
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="flex items-center gap-1 text-sm font-semibold text-default-700 px-0.5">
          {label}
          {required && <span className="text-danger text-sm leading-none">*</span>}
          {hint && <span className="text-[11px] font-normal text-default-400 mr-0.5">({hint})</span>}
        </label>
      )}
      {children}
      {error && (
        <p className="flex items-center gap-1 text-[11px] text-danger px-0.5">
          <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}
            strokeLinecap="round" strokeLinejoin="round"><circle cx={12} cy={12} r={10}/><path d="M12 8v4M12 16h.01"/></svg>
          {error}
        </p>
      )}
    </div>
  )
}

// ── TextField ─────────────────────────────────────────────────────────────────
export function TextField({
  label, hint, value, onChange, placeholder, type = 'text',
  description, startContent, endContent, isDisabled, dir, required, error,
}: {
  label?: string
  hint?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  description?: string
  startContent?: ReactNode
  endContent?: ReactNode
  isDisabled?: boolean
  dir?: 'rtl' | 'ltr'
  required?: boolean
  error?: string
}) {
  return (
    <Field label={label} hint={hint} required={required} error={error}>
      <Input
        value={value}
        onValueChange={onChange}
        placeholder={placeholder}
        type={type}
        variant="bordered"
        isDisabled={isDisabled}
        startContent={startContent}
        endContent={endContent}
        description={description}
        isInvalid={!!error}
        classNames={FIELD_INPUT}
        {...(dir ? { dir } : {})}
      />
    </Field>
  )
}

// ── TextArea ──────────────────────────────────────────────────────────────────
export function TextArea({
  label, hint, value, onChange, placeholder, minRows = 4, maxRows = 10,
  maxLength, required, error, description,
}: {
  label?: string
  hint?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  minRows?: number
  maxRows?: number
  maxLength?: number
  required?: boolean
  error?: string
  description?: string
}) {
  return (
    <Field label={label} hint={hint} required={required} error={error}>
      <Textarea
        value={value}
        onValueChange={onChange}
        placeholder={placeholder}
        variant="bordered"
        minRows={minRows}
        maxRows={maxRows}
        maxLength={maxLength}
        isInvalid={!!error}
        description={description}
        classNames={FIELD_TEXTAREA}
      />
    </Field>
  )
}

// ── SelectField ───────────────────────────────────────────────────────────────
export function SelectField({
  label, hint, value, onChange, options, placeholder, required, error,
}: {
  label?: string
  hint?: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  placeholder?: string
  required?: boolean
  error?: string
}) {
  return (
    <Field label={label} hint={hint} required={required} error={error}>
      <Select
        selectedKeys={value ? [value] : []}
        onSelectionChange={(keys) => {
          const k = Array.from(keys as Set<string>)[0]
          if (k != null) onChange(String(k))
        }}
        placeholder={placeholder}
        variant="bordered"
        isInvalid={!!error}
        classNames={{
          trigger:        FIELD_INPUT.inputWrapper,
          value:          'text-foreground text-sm',
          popoverContent: 'bg-content1 border border-divider shadow-lg rounded-xl',
        }}
      >
        {options.map(o => (
          <SelectItem key={o.value}>{o.label}</SelectItem>
        ))}
      </Select>
    </Field>
  )
}

// ── SectionCard ───────────────────────────────────────────────────────────────
// Consistent card shell for settings panels, permission lists, etc.
export function SectionCard({
  children, className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-2xl border border-divider bg-content1 shadow-sm p-5 space-y-4 ${className}`}>
      {children}
    </div>
  )
}

// ── SectionTitle ──────────────────────────────────────────────────────────────
// Replaces emoji+paragraph title pattern. Pass an SVG path string as `icon`.
export function SectionTitle({
  icon, title, description, iconColor = 'text-primary', iconBg = 'bg-primary/10',
}: {
  icon: string | string[]
  title: string
  description?: string
  iconColor?: string
  iconBg?: string
}) {
  const paths = Array.isArray(icon) ? icon : [icon]
  return (
    <div className="flex items-start gap-3">
      <div className={`w-9 h-9 rounded-xl ${iconBg} ${iconColor} flex items-center justify-center flex-shrink-0 mt-0.5`}>
        <svg width={18} height={18} viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          {paths.map((d, i) => <path key={i} d={d} />)}
        </svg>
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-bold text-sm text-foreground leading-tight">{title}</p>
        {description && <p className="text-[11px] text-default-400 mt-0.5 leading-relaxed">{description}</p>}
      </div>
    </div>
  )
}

// ── InlineAlert ───────────────────────────────────────────────────────────────
// Replaces the old Msg component. Shows success (green) or error (red).
export function InlineAlert({ text, className = '' }: { text: string; className?: string }) {
  if (!text) return null
  const ok = text.startsWith('✅') || text.startsWith('تم') || text.startsWith('نجح')
  return (
    <div className={`flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-sm border ${
      ok
        ? 'bg-success-50 border-success-200 text-success-700'
        : 'bg-danger-50  border-danger-200  text-danger-700'
    } ${className}`}>
      <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 mt-0.5">
        {ok
          ? <><circle cx={12} cy={12} r={10}/><path d="M9 12l2 2 4-4"/></>
          : <><circle cx={12} cy={12} r={10}/><path d="M12 8v4M12 16h.01"/></>
        }
      </svg>
      <span className="leading-relaxed">{text}</span>
    </div>
  )
}

// ── OptionCard ────────────────────────────────────────────────────────────────
// Single item in a grid of mutually exclusive choices (tone, language, length…)
export function OptionCard({
  label, sub, selected, onSelect,
}: {
  label: string
  sub?: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`relative text-right rounded-xl border p-3 transition-all duration-150 cursor-pointer
        ${selected
          ? 'border-primary bg-primary/8 ring-2 ring-primary/20 shadow-sm'
          : 'border-default-200 bg-default-50 hover:border-primary/40 hover:bg-content1'
        }`}>
      {selected && (
        <span className="absolute top-2 left-2 w-1.5 h-1.5 rounded-full bg-primary opacity-80" />
      )}
      <p className={`font-bold text-sm leading-tight ${selected ? 'text-primary' : 'text-foreground'}`}>
        {label}
      </p>
      {sub && (
        <p className="text-[11px] text-default-400 mt-0.5 leading-tight">{sub}</p>
      )}
    </button>
  )
}

// ── SaveBtn ───────────────────────────────────────────────────────────────────
// Consistent full-width primary save button — always teal, never blue gradient.
export function SaveBtn({
  label = 'حفظ', loading = false, onPress, size = 'md', fullWidth = true,
}: {
  label?: string
  loading?: boolean
  onPress?: () => void
  size?: 'sm' | 'md'
  fullWidth?: boolean
}) {
  return (
    <Button
      color="primary"
      isLoading={loading}
      onPress={onPress}
      size={size}
      className={`font-bold ${fullWidth ? 'w-full' : ''} ${size === 'sm' ? 'h-9' : 'h-11'}`}
    >
      {loading ? '' : label}
    </Button>
  )
}

// ── SubLabel ──────────────────────────────────────────────────────────────────
// Section sub-heading inside a card (replaces uppercase Arabic labels).
export function SubLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-xs font-bold text-default-500 mb-2">{children}</p>
  )
}
