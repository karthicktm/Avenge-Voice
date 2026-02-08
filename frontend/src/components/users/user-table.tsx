"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RoleBadge } from "@/components/auth/role-badge";
import { Badge } from "@/components/ui/badge";
import { MoreHorizontal, UserCheck, UserX, Pencil, Trash2, ShieldCheck } from "lucide-react";
import type { UserResponse, UserRole } from "@/lib/api/users";

interface UserTableProps {
  users: UserResponse[];
  currentUserId: number;
  currentUserRole: UserRole;
  onEdit: (user: UserResponse) => void;
  onDelete: (user: UserResponse) => void;
  onChangeRole: (user: UserResponse) => void;
  onToggleActive: (user: UserResponse) => void;
}

export function UserTable({
  users,
  currentUserId,
  currentUserRole,
  onEdit,
  onDelete,
  onChangeRole,
  onToggleActive,
}: UserTableProps) {
  const canManageUser = (targetUser: UserResponse) => {
    // Can't manage yourself
    if (targetUser.id === currentUserId) return false;
    // Super admins can manage everyone
    if (currentUserRole === "super_admin") return true;
    // Admins can manage users, but not other admins or super admins
    if (currentUserRole === "admin") {
      return targetUser.role === "user";
    }
    return false;
  };

  const canChangeRole = (targetUser: UserResponse) => {
    if (targetUser.id === currentUserId) return false;
    // Only super admins can change roles to/from admin
    if (currentUserRole === "super_admin") {
      // Can't change super_admin role
      return targetUser.role !== "super_admin";
    }
    return false;
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return "Never";
    return new Date(dateString).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>User</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Email Verified</TableHead>
            <TableHead>Last Login</TableHead>
            <TableHead>Created</TableHead>
            <TableHead className="w-[120px]">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                No users found.
              </TableCell>
            </TableRow>
          ) : (
            users.map((user) => (
              <TableRow key={user.id}>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-medium">{user.full_name ?? "Unnamed User"}</span>
                    <span className="text-sm text-muted-foreground">{user.email}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <RoleBadge role={user.role} />
                </TableCell>
                <TableCell>
                  {user.is_active ? (
                    <Badge variant="outline" className="border-green-500 text-green-600">
                      <UserCheck className="mr-1 h-3 w-3" />
                      Active
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="border-red-500 text-red-600">
                      <UserX className="mr-1 h-3 w-3" />
                      Inactive
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  {user.email_verified ? (
                    <Badge variant="outline" className="border-green-500 text-green-600">
                      Verified
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="border-yellow-500 text-yellow-600">
                      Pending
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(user.last_login_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(user.created_at)}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => onEdit(user)}
                      disabled={!canManageUser(user)}
                      title="Edit user"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => onDelete(user)}
                      disabled={!canManageUser(user)}
                      className="text-destructive hover:text-destructive"
                      title="Delete user"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon">
                          <MoreHorizontal className="h-4 w-4" />
                          <span className="sr-only">More actions</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {canChangeRole(user) && (
                          <DropdownMenuItem onClick={() => onChangeRole(user)}>
                            <ShieldCheck className="mr-2 h-4 w-4" />
                            Change Role
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                          onClick={() => onToggleActive(user)}
                          disabled={!canManageUser(user)}
                        >
                          {user.is_active ? (
                            <>
                              <UserX className="mr-2 h-4 w-4" />
                              Deactivate
                            </>
                          ) : (
                            <>
                              <UserCheck className="mr-2 h-4 w-4" />
                              Activate
                            </>
                          )}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
