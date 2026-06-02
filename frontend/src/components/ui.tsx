/**
 * Shared dashboard design system — thin, consistent wrappers over HeroUI v2
 * components. Centralising the field styling here means every form across
 * the dashboard looks identical and the label/placeholder never overlaps
 * (we render the label as an explicit element ABOVE the control, which is
 * reliable in RTL — HeroUI's labelPlacement="outside" overlaps its own
 * placeholder in Arabic).
 *
 * Usage:
 *   <TextField label="اسم البوت" hint="اختياري" value={v} onChange={setV}
 *              placeholder="مساعد المتجر" icon="..." />
 *   <TextArea  label="التوجيه" value={v} onChange={setV} minRows={4} />
 *   <SelectField label="المزود" value={p} onChange={setP} options={[...]} />
 */
import { Input, Textarea, Select, SelectItem } from '@heroui/react'
import type { ReactNode } from 'react'

// ── Shared HeroUI classNames (light design tokens — Purity-style) ────────────
// Comfortable height + clear padding so labels never overlap the value and the
// control reads as a proper, roomy field.
export const FIELD_INPUT = {
  inputWrapper:
    'border-default-200 bg-default-50 h-12 min-h-12 rounded-xl px-4 ' +
    'data-[hover=true]:border-default-300 ' +
    'group-data-[focus=true]:!border-primary group-data-[focus=true]:bg-content1 ' +
    'transition-colors',
  input: 'text-foreground text-sm placeholder:text-default-400',
}

export const FIELD_TEXTAREA = {
  inputWrapper:
    'border-default-200 bg-default-50 rounded-xl px-4 py-3 !h-auto items-start ' +
    'data-[hover=true]:border-default-300 ' +
    'group-data-[focus=true]:!border-primary group-data-[focus=true]:bg-content1 ' +
    'transition-colors',
  input: 'text-foreground text-sm leading-relaxed placeholder:text-default-400 py-0.5',
}

// ── Field: explicit label + optional hint above any control ──────────────────
export function Field({ label, hint, error, children }: {
  label?: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="space-y-2">
      {label && (
        <label className="flex items-center gap-1.5 text-sm font-semibold text-default-700 px-0.5">
          {label}
          {hint && <span className="text-[11px] font-normal text-default-400">({hint})</span>}
        </label>
      )}
      {children}
      {error && <p className="text-[11px] text-danger px-0.5">{error}</p>}
    </div>
  )
}

// ── TextField ────────────────────────────────────────────────────────────────
export function TextField({
  label, hint, value, onChange, placeholder, type = 'text',
  description, startContent, isDisabled, dir,
}: {
  label?: string
  hint?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  description?: string
  startContent?: ReactNode
  isDisabled?: boolean
  dir?: 'rtl' | 'ltr'
}) {
  return (
    <Field label={label} hint={hint}>
      <Input
        value={value}
        onValueChange={onChange}
        placeholder={placeholder}
        type={type}
        variant="bordered"
        isDisabled={isDisabled}
        startContent={startContent}
        description={description}
        classNames={FIELD_INPUT}
        {...(dir ? { dir } : {})}
      />
    </Field>
  )
}

// ── TextArea ─────────────────────────────────────────────────────────────────
export function TextArea({
  label, hint, value, onChange, placeholder, minRows = 4, maxRows = 10, maxLength,
}: {
  label?: string
  hint?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  minRows?: number
  maxRows?: number
  maxLength?: number
}) {
  return (
    <Field label={label} hint={hint}>
      <Textarea
        value={value}
        onValueChange={onChange}
        placeholder={placeholder}
        variant="bordered"
        minRows={minRows}
        maxRows={maxRows}
        maxLength={maxLength}
        classNames={FIELD_TEXTAREA}
      />
    </Field>
  )
}

// ── SelectField ──────────────────────────────────────────────────────────────
export function SelectField({
  label, hint, value, onChange, options, placeholder,
}: {
  label?: string
  hint?: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  placeholder?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <Select
        selectedKeys={value ? [value] : []}
        onSelectionChange={(keys) => {
          const k = Array.from(keys as Set<string>)[0]
          if (k != null) onChange(String(k))
        }}
        placeholder={placeholder}
        variant="bordered"
        classNames={{
          trigger: FIELD_INPUT.inputWrapper,
          value:   'text-foreground text-sm',
          popoverContent: 'bg-content1 border border-divider',
        }}
      >
        {options.map(o => (
          <SelectItem key={o.value}>{o.label}</SelectItem>
        ))}
      </Select>
    </Field>
  )
}
