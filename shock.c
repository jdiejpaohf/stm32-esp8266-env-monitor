#include "shock.h"
#include "stm32f10x.h"

void shock_init(void)
{
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure;

	// 2.打开外设时钟  PC1--GPIOC
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);

	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_1;	// 引脚配置
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;	// 引脚模式   上拉输入
	
	// 4.初始化GPIO
	GPIO_Init(GPIOC, &GPIO_InitStructure);

}
