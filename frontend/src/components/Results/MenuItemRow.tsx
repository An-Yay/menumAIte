import type { MenuItem } from "../../types/models";

interface MenuItemRowProps {
  item: MenuItem;
}

/** A single recommended dish. Price handling mirrors the backend contract
 * exactly: a price is shown only when `price_available` is true, otherwise
 * we state plainly that it isn't listed. Never a guessed number. */
export function MenuItemRow({ item }: MenuItemRowProps) {
  return (
    <li className="menu-item">
      <div className="menu-item__top">
        <span className="menu-item__name">{item.name}</span>
        <span className="menu-item__price">
          {item.price_available && item.price_amount != null
            ? `${item.price_amount.toFixed(2)} ${item.price_currency ?? ""}`.trim()
            : "Price not listed"}
        </span>
      </div>
      {item.original_name && item.original_name !== item.name && (
        <div className="menu-item__original">{item.original_name}</div>
      )}
      {item.description && <p className="menu-item__description">{item.description}</p>}
      {item.dietary_tags.length > 0 && (
        <div className="menu-item__tags">
          {item.dietary_tags.map((tag) => (
            <span key={tag} className="menu-item__tag">
              {tag}
            </span>
          ))}
        </div>
      )}
    </li>
  );
}
