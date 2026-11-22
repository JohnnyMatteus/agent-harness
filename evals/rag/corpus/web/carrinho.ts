export function somarItensDoCarrinho(itens: { preco: number; qtd: number }[]): number {
  return itens.reduce((acc, i) => acc + i.preco * i.qtd, 0);
}

export class CarrinhoDeCompras {
  private itens: string[] = [];

  esvaziarCarrinho(): void {
    this.itens = [];
  }
}

export const formatarMoeda = (valor: number): string => `R$ ${valor.toFixed(2)}`;
