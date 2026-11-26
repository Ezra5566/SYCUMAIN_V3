import type { LucideIcon } from "lucide-react";
import {
  LayoutDashboard,
  Users,
  GraduationCap,
  CalendarCheck,
  CalendarDays,
  Home,
  ShieldCheck,
  Globe2,
  Megaphone,
  LifeBuoy,
  Bell,
  FileText,
  BarChart3,
  ClipboardCheck,
  ClipboardList,
  ScrollText,
  Settings,
  UserRound,
} from "lucide-react";

export interface NavItem {
  /** Translation key within the `navigation` namespace. */
  labelKey: string;
  href?: string;
  icon: LucideIcon;
  /** Permission required to see this item. Omit for always-visible items. */
  permission?: string;
  /**
   * Roles explicitly excluded even when they hold the permission.
   * Mirrors backend object-level rules — a STUDENT holds `student.view`
   * (for their own record) but must never see the directory.
   */
  hiddenForRoles?: string[];
  /**
   * When set, only these roles see the item.
   *
   * The counterpart to `hiddenForRoles`, and it exists for the same reason:
   * `student.view` means "your own record" for a student but "the directory"
   * for staff, so a permission alone cannot express which surface is meant.
   */
  visibleForRoles?: string[];
  /** Rendered as a disabled "coming soon" entry when the route does not exist. */
  comingSoon?: boolean;
}

export interface NavSection {
  /** Translation key within the `navigation` namespace. */
  titleKey: string;
  items: NavItem[];
}

/**
 * Single source of truth for portal navigation.
 *
 * Visibility is UX only — the FastAPI backend remains the authorization
 * boundary and re-checks every request. `hiddenForRoles` exists because some
 * permissions are object-scoped: a student may view *their own* record, which
 * does not authorize a directory listing.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    titleKey: "menu",
    items: [
      { labelKey: "dashboard", href: "/app", icon: LayoutDashboard },
      {
        // Students are never shown the staff directory, so this is how they
        // reach their own record. The page resolves "me" from the session and
        // forwards to the canonical profile route.
        labelKey: "myProfile",
        href: "/app/profile",
        icon: UserRound,
        permission: "student.view",
        visibleForRoles: ["STUDENT"],
      },
      {
        // The personalised timetable is enrollment-aware and lives on the
        // student's own record. The profile route forwards the tab, so a
        // student reaches it without knowing their identifier.
        labelKey: "myTimetable",
        href: "/app/profile?tab=timetable",
        icon: CalendarDays,
        permission: "academic.view",
        visibleForRoles: ["STUDENT"],
      },
    ],
  },
  {
    titleKey: "students",
    items: [
      {
        // The shared institutional schedule is open to every authenticated
        // role. It is not the administrative Academics console and it is not
        // a personal timetable: it shows a whole offering's week.
        labelKey: "timetable",
        href: "/app/timetable",
        icon: CalendarDays,
        permission: "academic.view",
      },
      {
        labelKey: "students",
        href: "/app/students",
        icon: Users,
        permission: "student.view",
        hiddenForRoles: ["STUDENT"],
      },
      {
        labelKey: "academics",
        href: "/app/academics",
        icon: GraduationCap,
        permission: "academic.view",
        // The academics module is the institutional curriculum view. A
        // student's own courses and timetable live in their profile.
        hiddenForRoles: ["STUDENT"],
      },
      {
        labelKey: "admissionVerification",
        href: "/app/admissions/verification",
        icon: ShieldCheck,
        // Verification acts expose candidate evidence and actor attribution,
        // so this is a staff-only surface gated by the admission read
        // permission as well as the server-side console flag.
        permission: "academic.view_admissions",
        hiddenForRoles: ["STUDENT"],
      },
      {
        // The university calendar decides which days count at all. Admin and
        // Management administer it; teachers and students never see it.
        labelKey: "calendar",
        href: "/app/academics/calendar",
        icon: CalendarDays,
        permission: "attendance.manage_calendar",
        hiddenForRoles: ["STUDENT"],
      },
      {
        // Commencement is the date attendance is expected to count from. It is
        // approved by Admin/Management only, so students never see this entry.
        labelKey: "commencement",
        href: "/app/admissions/commencement",
        icon: CalendarCheck,
        permission: "attendance.manage_commencement",
        hiddenForRoles: ["STUDENT"],
      },
      {
        // Phase 3: attendance is a student-level figure derived from absences.
        // Staff record absences (teachers only for their own students) and see
        // the whole cohort; a student sees their own percentage and history on
        // the same page.
        labelKey: "attendance",
        href: "/app/attendance",
        icon: ClipboardCheck,
        permission: "attendance.view",
      },
      {
        // Examinations are an institutional event: a schedule, participating
        // sections and results that are published as a separate act. Teachers
        // see only their assigned sections, students only their enrollments.
        labelKey: "examinations",
        href: "/app/examinations",
        icon: ClipboardList,
        permission: "exams.view",
      },
      {
        labelKey: "housing",
        href: "/app/housing",
        icon: Home,
        // Browsing the dormitory exposes every room and its occupants, so it
        // needs `housing.view_all`; `housing.view` only covers one's own bed.
        permission: "housing.view_all",
      },
      {
        labelKey: "immigration",
        href: "/app/immigration",
        icon: Globe2,
        // The module is the cohort-wide overview, which exposes every
        // student's document status. `immigration.view` only covers one's own
        // record, so it must not be the gate here.
        permission: "immigration.view_all",
      },
    ],
  },
  {
    titleKey: "announcements",
    items: [
      {
        labelKey: "announcements",
        href: "/app/announcements",
        icon: Megaphone,
        permission: "announcement.view",
      },
      {
        labelKey: "notifications",
        href: "/app/notifications",
        icon: Bell,
        permission: "notifications.view",
      },
      {
        labelKey: "support",
        href: "/app/support",
        icon: LifeBuoy,
        permission: "support.view",
      },
      {
        labelKey: "documents",
        href: "/app/documents",
        icon: FileText,
        permission: "documents.view",
      },
    ],
  },
  {
    titleKey: "reports",
    items: [
      {
        labelKey: "reports",
        href: "/app/reports",
        icon: BarChart3,
        permission: "reports.view",
      },
      {
        labelKey: "audit",
        href: "/app/audit",
        icon: ScrollText,
        permission: "audit.view",
      },
      {
        // Staff/student account lifecycle is an Admin surface. Management's
        // delegated student-account work stays inside the student directory.
        labelKey: "accounts",
        href: "/app/accounts",
        icon: UserRound,
        permission: "users.manage",
      },
    ],
  },
  {
    titleKey: "account",
    items: [
      {
        // Personal settings (language, password, sessions) are available to
        // every signed-in account, so this item carries no permission. They
        // are deliberately outside the Reports group: they are not reporting.
        labelKey: "settings",
        href: "/app/settings",
        icon: Settings,
      },
    ],
  },
];

/** Flat list, useful for tests and for looking up a single item. */
export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);
