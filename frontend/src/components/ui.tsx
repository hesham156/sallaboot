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
 *   BrandLogo   — company logo via logo.dev CDN with initials fallback
 */
import { Input, Textarea, Select, SelectItem, Button, Spinner } from '@heroui/react'
import type { ReactNode, KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useState } from 'react'

// ── BrandLogo ─────────────────────────────────────────────────────────────────
// Fetches a company logo from logo.dev CDN. Falls back to a colored initials
// tile on error (network failure, unknown domain, etc.).

const LOGO_DEV_TOKEN = 'pk_X2A7SSz4RzO6g8lQo6EwdA'

export function BrandLogo({
  domain,
  fallbackColor = '#64748b',
  fallbackLabel = '',
  size = 36,
  rounded = 10,
}: {
  domain: string
  fallbackColor?: string
  fallbackLabel?: string
  size?: number
  rounded?: number
}) {
  const [failed, setFailed] = useState(false)
  const url = `https://img.logo.dev/${domain}?token=${LOGO_DEV_TOKEN}&size=80&format=png`

  if (failed) {
    const label = fallbackLabel || domain.split('.')[0].slice(0, 3).toUpperCase()
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
        <rect width={40} height={40} rx={rounded} fill={fallbackColor} />
        <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
          fill="white" fontWeight="bold" fontSize="12" fontFamily="system-ui">
          {label}
        </text>
      </svg>
    )
  }

  return (
    <img
      src={url}
      alt={domain}
      width={size}
      height={size}
      onError={() => setFailed(true)}
      style={{ borderRadius: rounded, objectFit: 'contain', background: '#f8fafc' }}
    />
  )
}

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

/* ════════════════════════════════════════════════════════════════════════════
   DASHBOARD DATA PRIMITIVES
   Theme-aware (token-driven, no hardcoded slate), accessible, data-dense.
   Style: "Data-Dense Dashboard" — scannable KPI cards, status colours,
   minimal padding, tabular figures. Use these everywhere instead of
   hand-rolling per-page cards so every screen looks identical in light/dark.
   ════════════════════════════════════════════════════════════════════════════ */

// Semantic tone → token classes. NEVER hardcode hex/slate in pages; pick a tone.
export type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'secondary' | 'default'

const TONES: Record<Tone, { text: string; bg: string; ring: string }> = {
  primary:   { text: 'text-primary',    bg: 'bg-primary/10',    ring: 'ring-primary/30' },
  success:   { text: 'text-success',    bg: 'bg-success/10',    ring: 'ring-success/30' },
  warning:   { text: 'text-warning',    bg: 'bg-warning/10',    ring: 'ring-warning/30' },
  danger:    { text: 'text-danger',     bg: 'bg-danger/10',     ring: 'ring-danger/30' },
  secondary: { text: 'text-secondary',  bg: 'bg-secondary/10',  ring: 'ring-secondary/30' },
  default:   { text: 'text-foreground', bg: 'bg-default-100',   ring: 'ring-default-300' },
}

// ── Icon ──────────────────────────────────────────────────────────────────────
// Single shared SVG renderer (Lucide-style stroke paths). Replaces the per-page
// `Icon` copies. Pass one path string or an array. Decorative by default;
// pass `title` to expose it to screen readers.
export function Icon({ paths, size = 16, className = '', strokeWidth = 2, title }: {
  paths: string | string[]
  size?: number
  className?: string
  strokeWidth?: number
  title?: string
}) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" className={className}
      role={title ? 'img' : undefined} aria-hidden={title ? undefined : true}
    >
      {title && <title>{title}</title>}
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

// ── DeltaBadge ──────────────────────────────────────────────────────────────
// Week-over-week / period delta. Direction shown by glyph + colour (not colour
// alone — satisfies WCAG color-not-only).
export function DeltaBadge({ value, suffix = '%' }: { value: number | null | undefined; suffix?: string }) {
  if (value == null) return null
  const up = value > 0, flat = value === 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-bold tabular-nums ${
      flat ? 'text-default-400' : up ? 'text-success' : 'text-danger'
    }`}>
      {flat ? '—' : up ? '▲' : '▼'}{!flat && `${Math.abs(value)}${suffix}`}
    </span>
  )
}

// ── StatCard ──────────────────────────────────────────────────────────────────
// The canonical KPI card. Optional onPress makes it a real keyboard-accessible
// button (Enter/Space), with focus ring + cursor.
export function StatCard({
  label, value, sub, icon, tone = 'default', delta, onPress, accent = false,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: string | string[]
  tone?: Tone
  delta?: number | null
  onPress?: () => void
  accent?: boolean   // tint the big number with the tone colour
}) {
  const t = TONES[tone]
  const clickable = !!onPress
  return (
    <div
      {...(clickable ? {
        role: 'button',
        tabIndex: 0,
        onClick: onPress,
        onKeyDown: (e: ReactKeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPress?.() }
        },
      } : {})}
      className={`rounded-2xl border border-divider bg-content1 p-4 sm:p-5 transition-all duration-200 ${
        clickable
          ? 'cursor-pointer hover:border-default-300 hover:shadow-md focus:outline-none focus-visible:ring-2 ' + t.ring
          : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold text-default-500">{label}</p>
        {icon && (
          <span className={`w-8 h-8 rounded-xl ${t.bg} ${t.text} flex items-center justify-center flex-shrink-0`}>
            <Icon paths={icon} size={16} />
          </span>
        )}
      </div>
      <div className="mt-2 flex items-end gap-2 flex-wrap">
        <p className={`text-2xl sm:text-3xl font-black leading-none tabular-nums ${accent ? t.text : 'text-foreground'}`}>
          {value}
        </p>
        <DeltaBadge value={delta} />
      </div>
      {sub && <p className="text-[11px] text-default-400 mt-2 leading-relaxed">{sub}</p>}
    </div>
  )
}

// ── PageHeader ──────────────────────────────────────────────────────────────
// Consistent page title block. `actions` render on the opposite side.
export function PageHeader({ title, subtitle, icon, iconTone = 'primary', actions }: {
  title: string
  subtitle?: string
  icon?: string | string[]
  iconTone?: Tone
  actions?: ReactNode
}) {
  const t = TONES[iconTone]
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        {icon && (
          <span className={`w-10 h-10 rounded-xl ${t.bg} ${t.text} flex items-center justify-center flex-shrink-0`}>
            <Icon paths={icon} size={20} />
          </span>
        )}
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-foreground leading-tight">{title}</h1>
          {subtitle && <p className="text-xs text-default-500 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  )
}

// ── StatusPill ──────────────────────────────────────────────────────────────
// Coloured dot + label for live/connected/degraded states. Dot + text = not
// colour-only.
export function StatusPill({ tone = 'default', label, pulse = false }: {
  tone?: Tone
  label: string
  pulse?: boolean
}) {
  const t = TONES[tone]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${t.bg} ${t.text}`}>
      <span className={`relative w-1.5 h-1.5 rounded-full bg-current ${pulse ? 'after:absolute after:inset-0 after:rounded-full after:bg-current after:animate-ping' : ''}`} />
      {label}
    </span>
  )
}

// ── DataCard ──────────────────────────────────────────────────────────────────
// Card shell with an icon+title header and a divider. Replaces the repeated
// "rounded card + header row" pattern across Overview/Analytics.
export function DataCard({
  title, icon, iconTone = 'primary', chip, action, children, className = '', bodyClassName = 'p-5',
}: {
  title?: string
  icon?: string | string[]
  iconTone?: Tone
  chip?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  const t = TONES[iconTone]
  return (
    <div className={`rounded-2xl border border-divider bg-content1 overflow-hidden ${className}`}>
      {(title || action) && (
        <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-divider">
          {icon && (
            <span className={`w-7 h-7 rounded-lg ${t.bg} ${t.text} flex items-center justify-center flex-shrink-0`}>
              <Icon paths={icon} size={15} />
            </span>
          )}
          {title && <h2 className="font-bold text-sm text-foreground">{title}</h2>}
          {chip}
          {action && <div className="mr-auto">{action}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  )
}

// ── EmptyState ──────────────────────────────────────────────────────────────
export function EmptyState({ icon, title, hint, action }: {
  icon?: string | string[]
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      {icon && (
        <span className="w-14 h-14 rounded-2xl bg-default-100 text-default-400 flex items-center justify-center mb-4">
          <Icon paths={icon} size={26} />
        </span>
      )}
      <p className="text-sm font-semibold text-default-600">{title}</p>
      {hint && <p className="text-xs text-default-400 mt-1 max-w-sm leading-relaxed">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

// ── StatSkeleton ──────────────────────────────────────────────────────────────
// Loading placeholder for a KPI row (skeleton instead of a blank spinner).
export function StatSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-2xl border border-divider bg-content1 p-5">
          <div className="h-3 w-20 bg-default-100 rounded animate-pulse" />
          <div className="h-8 w-16 bg-default-100 rounded mt-3 animate-pulse" />
          <div className="h-2.5 w-24 bg-default-100 rounded mt-3 animate-pulse" />
        </div>
      ))}
    </div>
  )
}
