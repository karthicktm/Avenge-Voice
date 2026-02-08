"use client";

import { Download, ExternalLink, FileText, AlertCircle, CheckCircle, Clock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useInvoices } from "@/hooks/use-billing";
import { formatCurrency } from "@/lib/api/billing";
import type { Invoice } from "@/lib/api/billing";

interface InvoiceListProps {
  limit?: number;
}

export function InvoiceList({ limit = 10 }: InvoiceListProps) {
  const { data: invoices, isLoading, error } = useInvoices(limit);

  if (isLoading) {
    return <InvoiceListSkeleton />;
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
          <p className="text-center text-muted-foreground">Failed to load invoices</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Invoice History</CardTitle>
        <CardDescription>View and download your past invoices</CardDescription>
      </CardHeader>

      <CardContent>
        {!invoices || invoices.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <FileText className="mb-4 h-12 w-12 text-muted-foreground" />
            <p className="mb-2 font-medium">No invoices yet</p>
            <p className="text-sm text-muted-foreground">
              Invoices will appear here after your first billing cycle
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.map((invoice) => (
                <InvoiceRow key={invoice.id} invoice={invoice} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

interface InvoiceRowProps {
  invoice: Invoice;
}

function InvoiceRow({ invoice }: InvoiceRowProps) {
  const StatusIcon =
    {
      paid: CheckCircle,
      open: Clock,
      draft: FileText,
      void: AlertCircle,
      uncollectible: AlertCircle,
    }[invoice.status] ?? FileText;

  const statusColor = {
    paid: "default",
    open: "secondary",
    draft: "outline",
    void: "destructive",
    uncollectible: "destructive",
  }[invoice.status] as "default" | "secondary" | "outline" | "destructive";

  return (
    <TableRow>
      <TableCell>
        <div>
          <p className="font-medium">{new Date(invoice.created_at).toLocaleDateString()}</p>
          {invoice.period_start && invoice.period_end && (
            <p className="text-xs text-muted-foreground">
              {new Date(invoice.period_start).toLocaleDateString()} -{" "}
              {new Date(invoice.period_end).toLocaleDateString()}
            </p>
          )}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant={statusColor}>
          <StatusIcon className="mr-1 h-3 w-3" />
          {invoice.status.charAt(0).toUpperCase() + invoice.status.slice(1)}
        </Badge>
      </TableCell>
      <TableCell>
        <p className="font-medium">{formatCurrency(invoice.total, invoice.currency)}</p>
        {invoice.status === "open" && invoice.amount_due > 0 && (
          <p className="text-xs text-muted-foreground">
            Due: {formatCurrency(invoice.amount_due, invoice.currency)}
          </p>
        )}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-2">
          {invoice.invoice_pdf_url && (
            <Button variant="ghost" size="sm" asChild>
              <a href={invoice.invoice_pdf_url} target="_blank" rel="noopener noreferrer">
                <Download className="mr-1 h-4 w-4" />
                PDF
              </a>
            </Button>
          )}
          {invoice.hosted_invoice_url && (
            <Button variant="ghost" size="sm" asChild>
              <a href={invoice.hosted_invoice_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="mr-1 h-4 w-4" />
                View
              </a>
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

function InvoiceListSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center justify-between py-2">
              <div className="flex items-center gap-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-5 w-16" />
                <Skeleton className="h-4 w-20" />
              </div>
              <div className="flex gap-2">
                <Skeleton className="h-8 w-16" />
                <Skeleton className="h-8 w-16" />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
