"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Plus, AlertCircle, Users, UserCheck, UserX, Loader2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/hooks/use-auth";
import { RequireAdmin } from "@/components/auth/require-role";
import { UserTable } from "@/components/users/user-table";
import { CreateUserDialog } from "@/components/users/create-user-dialog";
import { EditUserDialog } from "@/components/users/edit-user-dialog";
import { DeleteUserDialog } from "@/components/users/delete-user-dialog";
import { ChangeRoleDialog } from "@/components/users/change-role-dialog";
import { fetchUsers, updateUser, type UserResponse, type UserListResponse } from "@/lib/api/users";

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  // State
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isChangeRoleDialogOpen, setIsChangeRoleDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserResponse | null>(null);

  // Fetch users
  const { data, isLoading, error } = useQuery<UserListResponse>({
    queryKey: ["users", page, includeInactive],
    queryFn: () => fetchUsers(page, 20, includeInactive),
    enabled: !!currentUser,
  });

  // Toggle active mutation
  const toggleActiveMutation = useMutation({
    mutationFn: async (user: UserResponse) => {
      return updateUser(user.id, { is_active: !user.is_active });
    },
    onSuccess: (updatedUser) => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(`User ${updatedUser.is_active ? "activated" : "deactivated"} successfully`);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update user");
    },
  });

  const handleEdit = (user: UserResponse) => {
    setSelectedUser(user);
    setIsEditDialogOpen(true);
  };

  const handleDelete = (user: UserResponse) => {
    setSelectedUser(user);
    setIsDeleteDialogOpen(true);
  };

  const handleChangeRole = (user: UserResponse) => {
    setSelectedUser(user);
    setIsChangeRoleDialogOpen(true);
  };

  const handleToggleActive = (user: UserResponse) => {
    toggleActiveMutation.mutate(user);
  };

  const handleUserCreated = () => {
    void queryClient.invalidateQueries({ queryKey: ["users"] });
    toast.success("User created successfully");
  };

  const handleUserUpdated = () => {
    void queryClient.invalidateQueries({ queryKey: ["users"] });
    toast.success("User updated successfully");
  };

  const handleUserDeleted = () => {
    void queryClient.invalidateQueries({ queryKey: ["users"] });
    toast.success("User deleted successfully");
  };

  const handleRoleChanged = () => {
    void queryClient.invalidateQueries({ queryKey: ["users"] });
    toast.success("User role changed successfully");
  };

  const users = data?.users ?? [];
  const totalUsers = data?.total ?? 0;
  const activeUsers = users.filter((u) => u.is_active).length;
  const verifiedUsers = users.filter((u) => u.email_verified).length;

  if (error) {
    return (
      <RequireAdmin>
        <div className="space-y-6">
          <div>
            <h1 className="text-xl font-semibold">User Management</h1>
            <p className="text-sm text-muted-foreground">Manage users in your organization</p>
          </div>
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
              <h3 className="mb-2 text-lg font-semibold">Failed to load users</h3>
              <p className="text-sm text-muted-foreground">
                {error instanceof Error ? error.message : "An error occurred"}
              </p>
            </CardContent>
          </Card>
        </div>
      </RequireAdmin>
    );
  }

  return (
    <RequireAdmin>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">User Management</h1>
            <p className="text-sm text-muted-foreground">Manage users in your organization</p>
          </div>
          <Button size="sm" onClick={() => setIsCreateDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New User
          </Button>
        </div>

        {/* Stats Cards */}
        <div className="grid gap-3 md:grid-cols-3">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Total Users</p>
                  <p className="text-lg font-semibold">{totalUsers}</p>
                </div>
                <Users className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Active Users</p>
                  <p className="text-lg font-semibold">{activeUsers}</p>
                </div>
                <UserCheck className="h-4 w-4 text-green-500" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Verified Users</p>
                  <p className="text-lg font-semibold">{verifiedUsers}</p>
                </div>
                <UserX className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-4">
          <div className="flex items-center space-x-2">
            <Switch
              id="include-inactive"
              checked={includeInactive}
              onCheckedChange={setIncludeInactive}
            />
            <Label htmlFor="include-inactive" className="text-sm">
              Show inactive users
            </Label>
          </div>
        </div>

        {/* Users Table */}
        {isLoading ? (
          <Card>
            <CardContent className="flex items-center justify-center py-16">
              <Loader2 className="mr-2 h-6 w-6 animate-spin text-muted-foreground" />
              <p className="text-muted-foreground">Loading users...</p>
            </CardContent>
          </Card>
        ) : users.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16">
              <Users className="mb-4 h-16 w-16 text-muted-foreground/50" />
              <h3 className="mb-2 text-lg font-semibold">No users found</h3>
              <p className="mb-4 max-w-sm text-center text-sm text-muted-foreground">
                {includeInactive
                  ? "No users in your organization yet."
                  : "No active users found. Toggle 'Show inactive users' to see all users."}
              </p>
              <Button onClick={() => setIsCreateDialogOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                Create First User
              </Button>
            </CardContent>
          </Card>
        ) : (
          <UserTable
            users={users}
            currentUserId={currentUser?.id ?? 0}
            currentUserRole={currentUser?.role ?? "user"}
            onEdit={handleEdit}
            onDelete={handleDelete}
            onChangeRole={handleChangeRole}
            onToggleActive={handleToggleActive}
          />
        )}

        {/* Pagination */}
        {data && data.total > data.per_page && (
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Showing {(page - 1) * data.per_page + 1} to{" "}
              {Math.min(page * data.per_page, data.total)} of {data.total} users
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={page * data.per_page >= data.total}
              >
                Next
              </Button>
            </div>
          </div>
        )}

        {/* Dialogs */}
        <CreateUserDialog
          open={isCreateDialogOpen}
          onOpenChange={setIsCreateDialogOpen}
          onUserCreated={handleUserCreated}
          currentUserRole={currentUser?.role ?? "user"}
        />

        <EditUserDialog
          user={selectedUser}
          open={isEditDialogOpen}
          onOpenChange={setIsEditDialogOpen}
          onUpdated={handleUserUpdated}
        />

        <DeleteUserDialog
          user={selectedUser}
          open={isDeleteDialogOpen}
          onOpenChange={setIsDeleteDialogOpen}
          onDeleted={handleUserDeleted}
        />

        <ChangeRoleDialog
          user={selectedUser}
          open={isChangeRoleDialogOpen}
          onOpenChange={setIsChangeRoleDialogOpen}
          onRoleChanged={handleRoleChanged}
        />
      </div>
    </RequireAdmin>
  );
}
