interface PagePlaceholderProps {
  title: string
  description: string
}

export function PagePlaceholder({ title, description }: PagePlaceholderProps) {
  return (
    <div>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-neutral-500 dark:text-neutral-400">{description}</p>
    </div>
  )
}
